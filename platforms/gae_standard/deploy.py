#!/usr/bin/env python
import json
import os
import subprocess
import sys

import requests


INSTANCE_CLASSES = ('F1', 'F2', 'F4')


def run(cmd):
    subprocess.check_call(cmd.split())


def deploy_gae_standard_python2(project_name):
    """Deploys the python 2.7 version of the service.

    Deploys the service 6 times with different configurations -- 3 different
    machine types, each deployed twice. One copy from each pair will be capped
    at a single instance by setting the scaling limit (to measure single
    instance performance).
    """
    root_dir = os.path.abspath(os.path.dirname(__file__))
    # a default module is required, so deploy an empty app to it
    os.chdir(os.path.join(root_dir, 'default'))
    subprocess.check_call([
        'gcloud', 'app', 'deploy', '--quiet', '--project',
        project_name, '--version', 'v1'])
    # deploy a variety of configurations of our python 2.7 app
    py27_dir = os.path.join(root_dir, 'py27')
    py27_cfg_template_path = os.path.join(py27_dir, 'template.yaml')
    template_cfg = open(py27_cfg_template_path, 'r').read()
    py27_cfg_path = os.path.join(py27_dir, 'app.yaml')
    os.chdir(py27_dir)
    for icls in INSTANCE_CLASSES:
        for suffix in ('one', ''):
            service = 'py27%s%s' % (icls.lower(), suffix)
            new_cfg = template_cfg + '\n'.join([
                'service: ' + service,
                'instance_class: ' + icls])
            open(py27_cfg_path, 'w').write(new_cfg)
            subprocess.check_call([
                'gcloud', 'app', 'deploy', '--quiet', '--project',
                project_name, '--version', 'v1'])
            if suffix == 'one':
                set_scaling_limit(project_name, service, 1)
    os.remove(py27_cfg_path)


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
    deploy_gae_standard_python2(project_name)


if __name__ == '__main__':
    main()
