#!/usr/bin/env python
from collections import namedtuple
import json
import math
import os
import re
import subprocess
import sys
import time

import requests


INSTANCE_CLASSES = ('F1', 'F2', 'F4')
MAX_CONCURRENT_REQ = 80  # also in template.ymal (GAE max is 80)
TESTS = ('noop', 'sleep', 'data', 'memcache', 'dbtx', 'txtask')
NARROW_TESTS = ('noop', 'memcache', 'dbtx', 'txtask')

Entrypoint = namedtuple('Entrypoint', ('name', 'command'))
PendingDeployment = namedtuple('PendingDeployment', (
    'framework', 'version', 'service', 'cfg', 'deploy_cmd', 'post_deploy'))


class Runtime(namedtuple('Runtime', ('name', 'path', 'cfg', 'deployments'))):
    def add_deploy(self, project_name, framework, entrypoint, tests, post):
        is_default = (entrypoint.name == 'default')
        service = self.name
        if not entrypoint.command:
            entrypoint_cfg = ''
        else:
            entrypoint_cfg = 'entrypoint: ' + entrypoint.command
        for test in tests if not is_default else [None]:
            if not is_default:
                if test:
                    version = '-'.join([framework, entrypoint.name, test])
                else:
                    version = entrypoint.name
                cfg = self.cfg + '\n'.join([
                    'service: ' + service,
                    entrypoint_cfg,
                ])
            else:
                version = 'vdefault'
                cfg = self.cfg  # default is implied
                assert not entrypoint_cfg
            cmd = ['gcloud', 'app', 'deploy', '--quiet', '--no-promote',
                   '--project', project_name,
                   '--version', version]
            # beta app deploy is required to use VPC connector (for Redis)
            # which is required by new GAE runtimes (all but python 2.7)
            if 'runtime: python27' not in cfg:
                cmd.insert(1, 'beta')
            self.deployments.append(PendingDeployment(
                framework, version, service, cfg, cmd, post))

    def is_version_ignored(self, limit_to_versions, version):
        if limit_to_versions is None:
            return False
        for regex in limit_to_versions:
            if regex.search(version):
                return False
        return True

    def deploy_all(self, count, limit_to_versions):
        os.chdir(self.path)
        deploy_time_log_fn = os.path.join(
            os.path.abspath(os.path.dirname(__file__)),
            'deploy_log.tsv')
        with open(deploy_time_log_fn, 'a') as fout_deploy_log:
            for pd in self.deployments:
                if self.is_version_ignored(limit_to_versions, pd.version):
                    continue
                self.__use_framework(self.name, self.path, pd.framework)
                open('app.yaml', 'w').write(pd.cfg)
                start = time.time()
                subprocess.check_call(pd.deploy_cmd)
                end = time.time()
                print >> fout_deploy_log, '%s\t%f\t%s' % (
                    pd.service, end - start, pd.version)
                if pd.post_deploy:
                    pd.post_deploy(pd.service, pd.version)
                count += 1
                print 'deployment #%d completed' % count
        return count

    def print_stats(self, limit_to_versions):
        all_services = set([])
        all_service_version_pairs = set([])
        ignored_pairs = set([])
        for pd in self.deployments:
            all_services.add(pd.service)
            sv = '-'.join([pd.service, pd.version])
            all_service_version_pairs.add(sv)
            if self.is_version_ignored(limit_to_versions, pd.version):
                ignored_pairs.add(sv)
        print 'GAE %s - %d service(s) and %d service-version pair(s)%s' % (
            self.name, len(all_services), len(all_service_version_pairs),
            (' (%d ignored)' % len(ignored_pairs)) if ignored_pairs else '')
        return all_services, all_service_version_pairs, ignored_pairs

    @staticmethod
    def __use_framework(runtime, runtime_dir, framework):
        ext = 'js' if 'node' in runtime else 'py'
        main_path = os.path.join(runtime_dir, 'main.%s' % ext)
        framework_path = os.path.join(runtime_dir, '%s_main.%s' % (
            framework, ext))
        subprocess.check_call(['cp', framework_path, main_path])


class GAEStandardDeployer(object):
    def __init__(self, project_name, limit_to_versions):
        self.project_name = project_name
        # we will deploy the runtimes in the order they are added
        self.runtimes = []
        self.limit_to_versions = frozenset(limit_to_versions)

    def __get_runtime(self, runtime_name):
        for runtime in self.runtimes:
            if runtime.name == runtime_name:
                return runtime  # already added
        root_dir = os.path.abspath(os.path.dirname(__file__))
        runtime_dir = os.path.join(root_dir, runtime_name)
        for cfg_name in ('template-generated', 'template', 'app'):
            runtime_cfg_template_path = os.path.join(
                runtime_dir, '%s.yaml' % cfg_name)
            if os.path.exists(runtime_cfg_template_path):
                break
        template_cfg = open(runtime_cfg_template_path, 'r').read()
        runtime = Runtime(runtime_name, runtime_dir, template_cfg, [])
        self.runtimes.append(runtime)
        return runtime

    def add_deploy(self, runtime, framework, entrypoint, tests, post=None):
        self.__get_runtime(runtime).add_deploy(
            self.project_name, framework, entrypoint, tests, post)

    def deploy_all(self):
        count = 0
        for runtime in self.runtimes:
            count = runtime.deploy_all(count, self.limit_to_versions)

    def print_stats(self):
        all_services = set()
        all_service_version_pairs = set()
        ignored_pairs = set()
        for runtime in self.runtimes:
            ret = runtime.print_stats(self.limit_to_versions)
            all_services |= ret[0]
            all_service_version_pairs |= ret[1]
            ignored_pairs |= ret[2]
        print 'GAE TOTAL - %d service(s) and %d service-version pair(s)%s' % (
            len(all_services), len(all_service_version_pairs),
            (' (%d ignored)' % len(ignored_pairs)) if ignored_pairs else '')
        assert len(all_services) <= 105, "can't have more than 105 services"
        assert len(all_service_version_pairs) <= 210, ("can't have more than "
                                                       "210 versions")


def queue_gae_standard_python2_deployments(deployer):
    """Prepares the python 2.7 services.

    Creates each service 6 times with different configurations -- 3 different
    machine types, each deployed twice. One copy from each pair will be capped
    at a single instance by setting the scaling limit (to measure single
    instance performance).

    Total Versions = 3 * 6 = 18
    """
    # deploy a variety of configurations of our python 2.7 app
    for icls in INSTANCE_CLASSES:
        name = icls.lower() + '-solo'
        deployer.add_deploy('py27', 'webapp', Entrypoint(name, None), TESTS,
                            post=lambda service, version: set_scaling_limit(
                                deployer.project_name, service, version, 1))


def get_entrypoints_for_py3():
    """Returns entrypoints to test.

    Threaded tests try 1 and 2 workers (with 3 threads per worker).

    Non-threaded tests (processes & greenlets) try 1, 2 and 3 workers.
      gunicorn - sync, gevent, meinheld, uvicorn, and app engine default
      uwsgi - processes, gevent (only for workers==2)

    Each test is run with 2 different frameworks (Falcon and Flask) except
    uvicorn which is run with only 1 framework (FastAPI).
    """
    entrypoints = [
        Entrypoint('gunicorn-default', ''),  # use the default
    ]

    gunicorn = ('gunicorn --worker-class %s --workers %d '
                '--bind :$PORT main:app --log-level warning')
    uwsgi = ('uwsgi --http-socket :$PORT --wsgi-file main.py --callable app '
             '--disable-logging ')

    # multi-threaded processes (2 configurations to test)
    for i, (num_workers, num_threads) in enumerate([(1, 80), (1, 10)]):
        name = 'gunicorn-thread%dw%dt' % (num_workers, num_threads)
        cmd = (gunicorn + ' --threads=%d') % (
            'gthread', num_workers, num_threads)
        entrypoints.append(Entrypoint(name, cmd))
        name = 'uwsgi-thread%dw%dt' % (num_workers, num_threads)
        entrypoints.append(Entrypoint(name, uwsgi + (
            '--master --processes=%d --threads=%d' % (
                num_workers, num_threads))))
        if i:
            continue  # uvicorn cannot be told how many threads to use atm
        # ASGI ... under the hood, uses a threadpool for concurrency
        name = 'gunicorn-uvicorn%dw' % num_workers
        entrypoints.append(Entrypoint(name, gunicorn % (
            'uvicorn.workers.UvicornWorker', num_workers)))
        name = 'gunicorn-uvicorn-ctpe%dw' % num_workers
        entrypoints.append(Entrypoint(name, gunicorn % (
            'uvicorn.workers.UvicornWorker', num_workers)))

    # just a single worker for greenlet-based
    for num_workers in (1,):
        # greenlets
        # each worker can handle an equal share of connections (fine when work
        # is extremely uniform)
        max_conns_per_worker = int(math.ceil(MAX_CONCURRENT_REQ / num_workers))
        name = 'gunicorn-gevent%dw%dc' % (num_workers, max_conns_per_worker)
        cmd = (gunicorn +  ' --worker-connections=%d') % (
            'gevent', num_workers, max_conns_per_worker)
        entrypoints.append(Entrypoint(name, cmd))
        name = 'uwsgi-gevent%dw%dc' % (num_workers, max_conns_per_worker)
        entrypoints.append(Entrypoint(name, uwsgi + (
            '--gevent %d' % max_conns_per_worker)))
        # not compatible with grpc? gevent has a custom patcher for grpc ...
        #name = 'gunicorn-meinheld%dw' % num_workers
        #cmd = gunicorn % ('egg:meinheld#gunicorn_worker', num_workers)
        #entrypoints.append(Entrypoint(name, cmd))

    return entrypoints


def queue_gae_standard_python3_deployments(deployer):
    """Prepares python 3.7 services.

    Only deploys to one instance class. Varies server entrypoint instead.

    Total Versions = 156
    """
    # deploy a service to drain the tx task queue
    deployer.add_deploy(
        'py37', 'flask', Entrypoint('txtaskhandler', None), [None])

    # deploy a service for each desired entrypoint X framework X test combo
    for entrypoint in get_entrypoints_for_py3():
        if 'uvicorn' not in entrypoint.name:
            frameworks = ('falcon', 'flask',)
        else:
            frameworks = ('fastapi',)
        for framework in frameworks:
            deployer.add_deploy('py37', framework, entrypoint, TESTS)


def queue_gae_standard_node10_deployments(deployer):
    """Prepares the NodeJS 10 services.

    Total Versions = 2 * 6 = 12
    """
    for framework in ('express', 'fastify'):
        deployer.add_deploy('node10', framework,
                            Entrypoint('f1-solo', None), TESTS)


def set_scaling_limit(project_name, service, version, limit):
    import google.auth
    import google.auth.transport.requests
    creds = google.auth.default()[0]
    auth_req = google.auth.transport.requests.Request()
    creds.refresh(auth_req)
    headers = {
        'Authorization': 'Bearer ' + creds.token,
        'Accept': 'application/json',
        'Content-Type': 'application/json',
    }
    data = json.dumps(dict(automaticScaling=dict(
        standardSchedulerSettings=dict(
            maxInstances=limit))))
    print 'setting max instances to 1 for', service, version
    host = 'appengine.googleapis.com'
    path = '/v1/apps/%s/services/%s/versions/%s' % (
        project_name, service, version)
    mask = 'automaticScaling.standard_scheduler_settings.max_instances'
    url = 'https://%s%s?updateMask=%s' % (host, path, mask)
    resp = requests.patch(url, data=data, headers=headers)
    if resp.status_code != 200:
        raise Exception('setting max instances failed %s %s %d %s' % (
            service, version, resp.status_code, resp.text))


def main():
    if not sys.argv or 'deploy.py' in sys.argv[-1]:
        print 'USAGE: ./deploy.py PROJECT_NAME[:VERSIONS_TO_DEPLOY]'
        sys.exit(1)
    if ':' in sys.argv[-1]:
        project_name, limit_to_versions = sys.argv[-1].split(':')
        limit_to_versions = [re.compile(x)
                             for x in limit_to_versions.split(',')]
    else:
        project_name = sys.argv[-1]
        limit_to_versions = None
    deployer = GAEStandardDeployer(project_name, limit_to_versions)

    # every app engine project requires a default service
    deployer.add_deploy('default', 'webapp', Entrypoint('default', None), None)
    queue_gae_standard_python2_deployments(deployer)
    queue_gae_standard_python3_deployments(deployer)
    queue_gae_standard_node10_deployments(deployer)
    deployer.print_stats()
    deployer.deploy_all()


if __name__ == '__main__':
    main()
