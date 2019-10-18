#!/usr/bin/env python
# pylint: disable=missing-docstring
from collections import namedtuple
import json
import math
import os
import re
import subprocess
import sys
import time

import requests


CLOUD_RUN_MACHINE_TYPES = ('managed',
                           'n1-highcpu-2', 'n2-highcpu-2', 'c2-standard-4')
INSTANCE_CLASSES = ('F1', 'F2', 'F4')
MAX_CONCURRENT_REQ = 80  # also in template.ymal (GAE max is 80)

TESTS = ('noop', 'sleep', 'data', 'memcache', 'dbjson',
         'dbtx', 'txtask', 'dbindir', 'dbindirb')
PY3TESTS = tuple(list(TESTS) + ['ndbtx', 'ndbtxtask', 'ndbindir', 'ndbindirb'])
PLATFORMS_DIR = os.path.abspath(os.path.dirname(__file__))


class AbstractDeployer(object):
    """Helper class to deploy many services."""
    def __init__(self, project_name, limit_to_deploy_uids):
        self.project_name = project_name
        self.limit_to_deploy_uids = limit_to_deploy_uids
        self.groups = []

    def deploy_all(self):
        count = 0
        for group in self.groups:
            count = group.deploy_all(count, self.limit_to_deploy_uids)

    def print_stats(self):
        all_categories = set()
        all_deployment_uids = set()
        ignored_duids = set()
        for group in self.groups:
            ret = group.print_stats(self.limit_to_deploy_uids)
            all_categories |= ret[0]
            all_deployment_uids |= ret[1]
            ignored_duids |= ret[2]
        print '%s TOTAL - %d categories and %d deployment UID(s)%s' % (
            self.__class__.__name__[:-len('Deployer')],
            len(all_categories), len(all_deployment_uids),
            (' (%d ignored)' % len(ignored_duids)) if ignored_duids else '')
        self._verify_deploy_limits(all_categories, all_deployment_uids)

    @staticmethod
    def _verify_deploy_limits(all_categories, all_deployment_uids):
        raise NotImplementedError


class AbstractDeploymentGroup(namedtuple('AbstractDeploymentGroup', (
        'name', 'cfg', 'deployments'))):
    """Helper class to deploy a group of related services."""
    @staticmethod
    def is_ignored(limit_to_deploy_uids, deployment_uid):
        if limit_to_deploy_uids is None:
            return False
        for regex in limit_to_deploy_uids:
            if regex.search(deployment_uid):
                return False
        return True

    def deploy_all(self, count, limit_to_deploy_uids):
        deploy_time_log_fn = os.path.join(PLATFORMS_DIR, 'deploy_log.tsv')
        with open(deploy_time_log_fn, 'a') as fout_deploy_log:
            for x in self.deployments:
                if self.is_ignored(limit_to_deploy_uids, x.deployment_uid):
                    continue
                self._pre_deploy(x)
                start = time.time()
                subprocess.check_call(x.deploy_cmd)
                end = time.time()
                print >> fout_deploy_log, '%s\t%f\t%s' % (
                    x.deployment_category, end - start, x.deployment_uid)
                if x.post_deploy:
                    x.post_deploy(x)
                count += 1
                print 'deployment #%d completed' % count
        return count

    def print_stats(self, limit_to_deploy_uids):
        all_categories = set([])
        all_deployment_uids = set([])
        ignored_duids = set([])
        for x in self.deployments:
            all_categories.add(x.category)
            all_deployment_uids.add(x.deployment_uid)
            if self.is_ignored(limit_to_deploy_uids, x.deployment_uid):
                ignored_duids.add(x.deployment_uid)
        print '%s %s - %d categories(s) and %d deployment UID(s)%s' % (
            self.__class__.__name__[:-len('DeploymentGroup')],
            self.name, len(all_categories), len(all_deployment_uids),
            (' (%d ignored)' % len(ignored_duids)) if ignored_duids else '')
        return all_categories, all_deployment_uids, ignored_duids

    def _pre_deploy(self, x):
        """Called to setup files for deployment."""
        # no-op by default


class CloudRunDeployConfig(namedtuple('CloudRunDeployConfig', (
        'image', 'machine_type', 'service', 'deploy_cmd', 'post_deploy'))):
    @property
    def category(self):
        return self.machine_type

    @property
    def deployment_uid(self):
        return self.service

    @property
    def deployment_category(self):
        return '-'.join([self.image.runtime, self.machine_type])


class CloudRunImageConfig(namedtuple('CloudRunImageConfig', (
        'runtime', 'start_name', 'start_cmd'))):
    @property
    def name(self):
        return '%s-%s' % (self.runtime, self.start_name)


class CloudRunDeployer(AbstractDeployer):
    def __init__(self, project_name, limit_to_deploy_uids):
        AbstractDeployer.__init__(self, project_name, limit_to_deploy_uids)
        self.container_images = set()
        self.groups = [
            CloudRunDeploymentGroup(machine_type, None, [])
            for machine_type in CLOUD_RUN_MACHINE_TYPES]
        self.__queue_cloud_run_deployments()

    def add_image(self, tests, image_cfg):
        for x in self.container_images:
            # repeats would cause a conflicting image name
            assert x.name != image_cfg.name
        self.container_images.add(image_cfg)
        for group in self.groups:
            group.add_image(self.project_name, tests, image_cfg)

    def deploy_all(self):
        images = sorted(self.container_images)
        for i, image in enumerate(images):
            print 'building image %d of %d' % (i + 1, len(images))
            self.build_image(image)
        AbstractDeployer.deploy_all(self)

    @staticmethod
    def _verify_deploy_limits(all_categories, all_deployment_uids):
        assert len(all_deployment_uids) / len(all_categories) <= 150, (
            "can't have more than 150 services per cluster")

    @staticmethod
    def build_image(image_cfg):
        os.chdir(PLATFORMS_DIR)
        # create the Dockerfile for this image
        template_dockerfile_fn = 'cloud_run/Dockerfile.%s' % image_cfg.runtime
        template_dockerfile_raw = open(template_dockerfile_fn, 'r').read()
        lines = [x for x in template_dockerfile_raw.split('\n') if x]
        if lines[-1].startswith('CMD '):
            lines = lines[:-1]  # will insert our own custom start command
        template_dockerfile = '\n'.join(lines)
        redis_info = open('cloud_run/.redis_info', 'r').read()
        dockerfile = '\n'.join([template_dockerfile,
                                redis_info,
                                'CMD ' + image_cfg.start_cmd, ''])
        with open('Dockerfile', 'w') as fout:
            fout.write(dockerfile)
        # create the cloud build config file for this image
        cloud_build_template = open(
            'cloud_run/cloudbuild-template.yaml', 'r').read()
        with open('cloudbuild.yaml', 'w') as fout:
            fout.write(cloud_build_template.replace('IMAGENAME',
                                                    image_cfg.name))
        # build the image
        print 'building image %s' % image_cfg.name
        subprocess.check_call(['gcloud', 'builds', 'submit'])

    def __queue_cloud_run_deployments(self):
        """Prepares the Cloud Run services.

        Creates services for each Cloud Run machine type we're testing. Creates
        a service for each combination of test and runtimes-framework pairs.

        Total Services = 8 * 9 = 72 per machine type
        """
        images = [
            CloudRunImageConfig('node10', 'express', 'express_main.js'),
            CloudRunImageConfig('node10', 'fastify', 'fastify_main.js'),
        ]

        py_servers = dict(
            gunicorn=dict(
                cmd=('exec gunicorn --worker-class %s --workers 2 '
                     '--bind :$PORT falcon_main:app --error-logfile=- '
                     '--log-level warning'),
                workers=[
                    'gevent --worker-connections 40',
                    'gthread --threads=10',
                    'uvicorn.workers.UvicornWorker'
                ],
            ),
            uwsgi=dict(
                cmd=('uwsgi --http-socket :$PORT --wsgi-file falcon_main.py '
                     '--callable app --disable-logging --%s 40'),
                workers=[
                    'gevent'
                ],
            ),
        )
        for runtime in ('py3', 'pypy3'):
            for server_type, cfg in py_servers.iteritems():
                for worker_info in cfg['workers']:
                    worker_type = worker_info.split(' ', 1)[0].split('.', 1)[0]
                    name = '%s-%s' % (server_type, worker_type)
                    cmd = cfg['cmd'] % worker_info
                    images.append(CloudRunImageConfig(runtime, name, cmd))

        for image in images:
            self.add_image(TESTS, image)


class CloudRunDeploymentGroup(AbstractDeploymentGroup):
    """A Cloud Run deployment group consists of a single machine type.

    All deployments for a group are part of the same GKE cluster. Each
    deployment will be a separate service on that cluster.
    """
    @property
    def machine_type(self):
        return self.name

    def add_image(self, project_name, tests, image_cfg):
        image = 'gcr.io/%s/%s:latest' % (project_name, image_cfg.name)
        if self.machine_type == 'managed':
            service_account = 'forcloudrun@%s.iam.gserviceaccount.com' % (
                project_name)
            deploy_cmd_extra = [
                '--platform', 'managed',
                '--allow-unauthenticated',
                '--region', 'us-central1',
                '--service-account', service_account,
            ]
        else:
            if self.machine_type == 'c2-standard-4':
                zone = 'us-central1-b'
            else:
                zone = 'us-central1-a'
            deploy_cmd_extra = [
                '--platform', 'gke',
                '--cluster', 'cluster-%s' % self.machine_type,
                '--cluster-location', zone,
                '--timeout', '900',
                '--cpu', '1.4',
                '--memory', '512Mi']

        for test in tests:
            service_name = '-'.join([self.machine_type,
                                     image_cfg.name,  # runtime and start name
                                     test])
            deploy_cmd = ['gcloud', 'beta', 'run', 'deploy', service_name,
                          '--image', image,
                          '--concurrency', '80',
                          '--max-instances', '1'] + deploy_cmd_extra
            post_deploy = None
            if self.machine_type != 'managed':
                post_deploy = self.post_deploy
            self.deployments.append(CloudRunDeployConfig(
                image_cfg, self.machine_type, service_name, deploy_cmd,
                post_deploy))

    @staticmethod
    def post_deploy(cr_deploy_cfg):  # pylint: disable=unused-argument
        print ('TODO: use gcloud alpha run services replace to set '
               'CPU request & limit %s')


Entrypoint = namedtuple('Entrypoint', ('name', 'command'))


class GAEDeployConfig(namedtuple('GAEDeployConfig', (
        'framework', 'version', 'service', 'cfg', 'deploy_cmd',
        'post_deploy', 'path'))):
    @property
    def category(self):
        return self.service

    @property
    def deployment_uid(self):
        return '-'.join([self.service, self.version])

    @property
    def deployment_category(self):
        return self.service


class GAEDeployer(AbstractDeployer):
    def __init__(self, project_name, limit_to_deploy_uids):
        AbstractDeployer.__init__(self, project_name, limit_to_deploy_uids)

    @property
    def runtimes(self):
        # we will deploy the runtimes in the order they are added
        return self.groups

    def __get_runtime(self, runtime_name):
        for runtime in self.runtimes:
            if runtime.name == runtime_name:
                return runtime  # already added
        root_dir = os.path.join(PLATFORMS_DIR, 'gae_standard')
        runtime_dir = os.path.join(root_dir, runtime_name)
        for cfg_name in ('template-generated', 'template', 'app'):
            runtime_cfg_template_path = os.path.join(
                runtime_dir, '%s.yaml' % cfg_name)
            if os.path.exists(runtime_cfg_template_path):
                break
        template_cfg = open(runtime_cfg_template_path, 'r').read()
        runtime = GAEDeploymentGroup(runtime_name, template_cfg, [])
        self.runtimes.append(runtime)
        return runtime

    def add_deploy(self, runtime, framework, entrypoint, tests, post=None):
        self.__get_runtime(runtime).add_deploy(
            self.project_name, framework, entrypoint, tests, post)

    @staticmethod
    def _verify_deploy_limits(all_categories, all_deployment_uids):
        assert len(all_categories) <= 105, "can't have more than 105 services"
        assert len(all_deployment_uids) <= 210, (
            "can't have more than 210 versions")


class GAEDeploymentGroup(AbstractDeploymentGroup):
    """A GAE deployment group consists of a single runtime (e.g., python 2.7).

    All deployments for a GAE deployment group are part of the same service
    (e.g., py27). The service has many versions (one for each combination of
    framework (e.g., falcon), entrypoint (e.g., guicorn+gevent w/2 workers) and
    test.
    """
    @property
    def runtime(self):
        return self.name

    def add_deploy(self, project_name, framework, entrypoint, tests, post):
        is_default = (entrypoint.name == 'default')
        service = self.runtime
        root_dir = os.path.join(PLATFORMS_DIR, 'gae_standard')
        runtime_dir = os.path.join(root_dir, self.runtime)
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
            self.deployments.append(GAEDeployConfig(
                framework, version, service, cfg, cmd, post, runtime_dir))

    def _pre_deploy(self, gae_deploy_cfg):
        os.chdir(gae_deploy_cfg.path)
        self.__use_framework(self.runtime, gae_deploy_cfg.path,
                             gae_deploy_cfg.framework)
        open('app.yaml', 'w').write(gae_deploy_cfg.cfg)

    @staticmethod
    def __use_framework(runtime, runtime_dir, framework):
        ext = 'js' if 'node' in runtime else 'py'
        main_path = os.path.join(runtime_dir, 'main.%s' % ext)
        framework_path = os.path.join(runtime_dir, '%s_main.%s' % (
            framework, ext))
        subprocess.check_call(['cp', framework_path, main_path])


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
                            post=lambda x: set_scaling_limit(
                                deployer.project_name,
                                x.service, x.version, 1))


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
        name = 'gunicorn-thrd%dw%dt' % (num_workers, num_threads)
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
        #name = 'gunicorn-uvicorn%dw' % num_workers
        #entrypoints.append(Entrypoint(name, gunicorn % (
        #    'uvicorn.workers.UvicornWorker', num_workers)))
        name = 'gunicorn-uv2-%dw' % num_workers
        entrypoints.append(Entrypoint(name, gunicorn % (
            'uvicorn.workers.UvicornWorker', num_workers)))

    # just a single worker for greenlet-based
    for num_workers in (1,):
        # greenlets
        # each worker can handle an equal share of connections (fine when work
        # is extremely uniform)
        max_conns_per_worker = int(math.ceil(MAX_CONCURRENT_REQ / num_workers))
        name = 'gunicorn-gevent%dw' % num_workers
        cmd = (gunicorn % (
            'gevent', num_workers)) + ' --worker-connections %d' % (
                max_conns_per_worker)
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
        if 'uv' not in entrypoint.name:
            frameworks = (
                'falcon',
                'flask',
            )
        else:
            frameworks = ('fastapi',)
        for framework in frameworks:
            # need to limit tests a bit so we don't have too many versions
            tests = PY3TESTS
            if framework == 'flask':
                tests = TESTS  # no ndb tests for flask
                if 'uwsgi' in entrypoint.name:
                    continue  # no uwsgi tests for flask
            deployer.add_deploy('py37', framework, entrypoint, tests)


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
        print 'USAGE: ./deploy.py PROJECT_NAME[:DEPLOYMENT_IDS_TO_DEPLOY]'
        sys.exit(1)
    if ':' in sys.argv[-1]:
        project_name, limit_to_deploy_uids = sys.argv[-1].split(':')
        limit_to_deploy_uids = frozenset(
            [re.compile(x) for x in limit_to_deploy_uids.split(',')])
    else:
        project_name = sys.argv[-1]
        limit_to_deploy_uids = None

    deployer = GAEDeployer(project_name, limit_to_deploy_uids)
    # every app engine project requires a default service
    deployer.add_deploy('default', 'webapp', Entrypoint('default', None), None)
    queue_gae_standard_python2_deployments(deployer)
    queue_gae_standard_python3_deployments(deployer)
    queue_gae_standard_node10_deployments(deployer)
    deployer.print_stats()

    cr_deployer = CloudRunDeployer(project_name, limit_to_deploy_uids)
    cr_deployer.print_stats()

    deployer.deploy_all()
    cr_deployer.deploy_all()


if __name__ == '__main__':
    main()
