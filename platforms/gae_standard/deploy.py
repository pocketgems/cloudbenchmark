#!/usr/bin/env python
from collections import namedtuple
import json
import math
import os
import subprocess
import sys

import requests


INSTANCE_CLASSES = ('F1', 'F2', 'F4')
MAX_CONCURRENT_REQ = 80  # also in template.ymal (GAE max is 80)
TESTS = ('noop', 'sleep', 'data', 'memcache', 'dbtx', 'txtask')
NARROW_TESTS = ('noop', 'memcache', 'dbtx', 'txtask')


def run(cmd):
    subprocess.check_call(cmd.split())


class GAEStandardDeployer(object):
    def __init__(self):
        self.deployments = []


def deploy_gae_standard_python2(project_name):
    """Deploys the python 2.7 version of the service.

    Deploys the service 6 times with different configurations -- 3 different
    machine types, each deployed twice. One copy from each pair will be capped
    at a single instance by setting the scaling limit (to measure single
    instance performance). Required default service is deployed too.

    Total Services = 1 + 3 * 6 = 19
    """
    root_dir = os.path.abspath(os.path.dirname(__file__))
    # a default module is required, so deploy an empty app to it
    os.chdir(os.path.join(root_dir, 'default'))
    subprocess.check_call([
        'gcloud', 'app', 'deploy', '--quiet', '--project',
        project_name, '--version', 'v1'])
    # deploy the task queue configuration
    py27_dir = os.path.join(root_dir, 'py27')
    os.chdir(py27_dir)
    subprocess.check_call(['gcloud', 'app', 'deploy', 'queue.yaml', '--quiet',
                           '--project', project_name])
    # deploy a variety of configurations of our python 2.7 app
    py27_cfg_template_path = os.path.join(py27_dir, 'template.yaml')
    template_cfg = open(py27_cfg_template_path, 'r').read()
    py27_cfg_path = os.path.join(py27_dir, 'app.yaml')
    for icls in INSTANCE_CLASSES:
        for test in TESTS:
            service = 'py27-%s-solo-%s' % (icls.lower(), test)
            new_cfg = template_cfg + '\n'.join([
                'service: ' + service,
                'instance_class: ' + icls])
            open(py27_cfg_path, 'w').write(new_cfg)
            subprocess.check_call([
                'gcloud', 'app', 'deploy', '--quiet', '--project',
                project_name, '--version', 'v1'])
            set_scaling_limit(project_name, service, 1)
    os.remove(py27_cfg_path)


Entrypoint = namedtuple('Entrypoint', ('name', 'command'))


def get_entrypoints_for_py3():
    """Returns entrypoints to test.

    py37taskhandler service - handles the tx tasks

    Threaded tests try 1 and 2 workers (with 3 threads per worker).

    Non-threaded tests (processes & greenlets) try 1, 2 and 3 workers.
      gunicorn - sync, gevent, meinheld, uvicorn, and app engine default
      uwsgi - processes, gevent

    Using a narrower set of 4 tests due to GAE only allowing 105 services.
    Total Services = 1 + (2 threaded * 2 + 3 non-threaded * (5 + 2)) * 4 tests
                   = 1 + (1 + 4 + 18) * 4 = 93
    Only run uwsgi processes for workers==2 (not 1 or 3) --> -2*4 => 85

    Only have room for 105 (max) - 19 (py27 services) = 86. So 85 is fine.
    """
    entrypoints = [
        Entrypoint('default', ''),  # use the default
    ]

    gunicorn = ('gunicorn --preload --worker-class=%s --workers=%d'
                '--bind=:$PORT main:app --log-level warning')
    uwsgi = 'uwsgi --http :$PORT --wsgi-file main.py --callable app '

    # multi-threaded processes (2 configurations to test)
    for num_workers, num_threads in ((1, 3), (2, 3)):
        name = 'gunicorn-thread%dw%dt' % (num_workers, num_threads)
        cmd = (gunicorn + ' --num_threads=%d') % (
            'gthread', num_workers, num_threads)
        entrypoints.append(Entrypoint(name, cmd))
        name = 'uwsgi-thread%dw%dt' % (num_workers, num_threads)
        entrypoints.append(Entrypoint(name, uwsgi + (
            '--processes=%d --threads=%d' % (num_workers, num_threads))))

    # 3 worker amounts to test for everything else
    for num_workers in (1, 2, 3):
        # processes
        name = 'gunicorn-processes%dw' % num_workers
        entrypoints.append(Entrypoint(name, gunicorn % ('sync', num_workers)))
        if num_workers == 2:
            name = 'uwsgi-processes%dw' % num_workers
            entrypoints.append(Entrypoint(name, uwsgi + (
                '--processes=%d' % num_workers)))

        # greenlets
        # each worker can handle an equal share of connections (fine when work
        # is extremely uniform)
        max_conns_per_worker = int(math.ceil(MAX_CONCURRENT_REQ / num_workers))
        name = 'gunicorn-gevent%dw%dc' % (num_workers, max_conns_per_worker)
        cmd = (gunicorn +  '--worker-connections=%d') % (
            'gevent', num_workers, max_conns_per_worker)
        entrypoints.append(Entrypoint(name, cmd))
        name = 'uwsgi-gevent%dw%dc' % (num_workers, max_conns_per_worker)
        entrypoints.append(Entrypoint(name, uwsgi + (
            '--processes=%d --gevent=%d' % (num_workers,
                                            max_conns_per_worker))))
        name = 'gunicorn-meinheld%dw' % num_workers
        cmd = gunicorn % ('egg:meinheld#gunicorn-worker', num_workers)
        entrypoints.append(Entrypoint(name, cmd))

        # ASGI
        name = 'gunicorn-uvicorn%dw' % num_workers
        entrypoints.append(Entrypoint(name, gunicorn % (
            'uvicorn.workers.UvicornWorker', num_workers)))
    return entrypoints


PendingDeployment = namedtuple('PendingDeployment', (
    'framework_aka_version', 'service', 'cfg', 'deploy_cmd'))


def deploy_gae_standard_python3(project_name):
    """Deploys the python 3.7 version of the service.

    Only deploys to one instance class. Varies server entrypoint instead.
    """
    root_dir = os.path.abspath(os.path.dirname(__file__))
    py37_dir = os.path.join(root_dir, 'py37')
    py37_cfg_path = os.path.join(py37_dir, 'app.yaml')
    py37_cfg_template_path = os.path.join(py37_dir, 'template-with-redis.yaml')
    template_cfg = open(py37_cfg_template_path, 'r').read()
    os.chdir(py37_dir)

    def use_framework(framework):
        main_path = os.path.join(py37_dir, 'main.py')
        framework_path = os.path.join(py37_dir, '%s_main.py' % framework)
        subprocess.check_call(['cp', framework_path, main_path])


    deployments = []
    def add_deploy(framework, entrypoint, tests=NARROW_TESTS):
        version = framework
        for test in tests:
            if test:
                service = entrypoint.name + '-' + test
            else:
                service = entrypoint.name
            if not entrypoint.command:
                entrypoint_cfg = ''
            else:
                entrypoint_cfg = 'entrypoint: ' + entrypoint.command
            cfg = template_cfg + '\n'.join([
                'service: ' + service,
                entrypoint_cfg,
            ])
            # note: beta app deploy required to use VPC connector (for Redis)
            cmd = ['gcloud', 'beta', 'app', 'deploy', '--quiet', '--project',
                   project_name, '--version', version]
            deployments.append(PendingDeployment(framework, service, cfg, cmd))


    def deploy(pd):
        use_framework(pd.framework_aka_version)
        open(py37_cfg_path, 'w').write(pd.cfg)
        subprocess.check_call(pd.deploy_cmd)


    # deploy a service to drain the tx task queue
    add_deploy('flask', Entrypoint('py3taskhandler', None), [''])
    # deploy a service for each desired entrypoint X framework X test combo
    for entrypoint in get_entrypoints_for_py3():
        if 'uvicorn' not in entrypoint.name:
            frameworks = ('falcon', 'flask',)
        else:
            frameworks = ('fastapi',)
        for framework in frameworks:
            add_deploy(framework, entrypoint)

    all_services = set([])
    all_version_service_pairs = set([])
    for pd in deployments:
        all_services.add(pd.service)
        all_version_service_pairs.add('-'.join([pd.framework_aka_version,
                                                pd.service]))
    print 'GAE Python 3 - deploying %d services (%d service-version pairs)' % (
        len(all_services), len(all_version_service_pairs))


def set_scaling_limit(project_name, service, limit):
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
    print 'setting max instances to 1 for', service
    host = 'appengine.googleapis.com'
    path = '/v1/apps/%s/services/%s/versions/v1' % (
        project_name, service)
    mask = 'automaticScaling.standard_scheduler_settings.max_instances'
    url = 'https://%s%s?updateMask=%s' % (host, path, mask)
    resp = requests.patch(url, data=data, headers=headers)
    if resp.status_code != 200:
        raise Exception('setting max instances failed %s %d %s' % (
            service, resp.status_code, resp.text))


def main():
    if not sys.argv:
        print 'missing command-line arg'
        sys.exit(1)
    project_name = sys.argv[-1]
    #deploy_gae_standard_python2(project_name)
    deploy_gae_standard_python3(project_name)


if __name__ == '__main__':
    main()
