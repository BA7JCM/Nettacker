#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import socks
import socket
import time
from glob import glob
from io import StringIO


def getaddrinfo(*args):
    """
    same getaddrinfo() used in socket except its resolve addresses with socks proxy

    Args:
        args: *args

    Returns:
        getaddrinfo
    """
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (args[0], args[1]))]


def set_socks_proxy(socks_proxy):
    if socks_proxy:
        socks_version = socks.SOCKS5 if socks_proxy.startswith('socks5://') else socks.SOCKS4
        socks_proxy = socks_proxy.split('://')[1] if '://' in socks_proxy else socks_proxy
        if '@' in socks_proxy:
            socks_username = socks_proxy.split(':')[0]
            socks_password = socks_proxy.split(':')[1].split('@')[0]
            socks.set_default_proxy(
                socks_version,
                str(socks_proxy.rsplit('@')[1].rsplit(':')[0]),  # hostname
                int(socks_proxy.rsplit(':')[-1]),  # port
                username=socks_username,
                password=socks_password
            )
        else:
            socks.set_default_proxy(
                socks_version,
                str(socks_proxy.rsplit(':')[0]),  # hostname
                int(socks_proxy.rsplit(':')[1])  # port
            )
        return socks.socksocket, getaddrinfo
    else:
        return socket.socket, socket.getaddrinfo


class NettackerModules:
    def __init__(self):
        self.module_name = None
        self.module_content = None
        self.scan_unique_id = None
        self.target = None
        self.module_inputs = {}
        self.libraries = [
            'http',
            'socket'
        ]

    def load(self):
        import yaml
        from config import nettacker_paths
        from core.utility import find_and_replace_configuration_keys
        self.module_content = find_and_replace_configuration_keys(
            yaml.load(
                StringIO(
                    open(
                        nettacker_paths()['modules_path'] +
                        '/' +
                        self.module_name.split('_')[-1].split('.yaml')[0] +
                        '/' +
                        '_'.join(self.module_name.split('_')[:-1]) +
                        '.yaml',
                        'r'
                    ).read().format(
                        **self.module_inputs
                    )
                ),
                Loader=yaml.FullLoader
            ),
            self.module_inputs
        )

    def generate_loops(self):
        from core.utility import expand_module_steps
        self.module_content['payloads'] = expand_module_steps(self.module_content['payloads'])

    def start(self):
        from terminable_thread import Thread
        from core.utility import wait_for_threads_to_finish
        active_threads = []
        from core.alert import warn

        for payload in self.module_content['payloads']:
            if payload['library'] not in self.libraries:
                warn('library [{library}] is not support!'.format(library=payload['library']))
                return None
            protocol = getattr(
                __import__(
                    'core.module_protocols.{library}'.format(library=payload['library']),
                    fromlist=['engine']
                ),
                'engine'
            )
            for step in payload['steps']:
                for sub_step in step:
                    thread = Thread(
                        target=protocol.run,
                        args=(
                            sub_step,
                            self.module_name,
                            self.target,
                            self.scan_unique_id,
                            self.module_inputs
                        )
                    )
                    thread.name = f"{self.target} -> {self.module_name} -> {sub_step}"
                    thread.start()
                    time.sleep(self.module_inputs['time_sleep_between_requests'])
                    active_threads.append(thread)
                    wait_for_threads_to_finish(
                        active_threads,
                        maximum=self.module_inputs['thread_per_host'],
                        terminable=True
                    )
        wait_for_threads_to_finish(
            active_threads,
            maximum=None,
            terminable=True
        )


def load_all_graphs():
    """
    load all available graphs

    Returns:
        an array of graph names
    """
    from config import nettacker_paths
    graph_names = []
    for graph_library in glob(os.path.join(nettacker_paths()['home_path'] + '/lib/graph/*/engine.py')):
        graph_names.append(graph_library.split('/')[-2] + '_graph')
    return graph_names


def load_all_languages():
    """
    load all available languages

    Returns:
        an array of languages
    """
    languages_list = []
    from config import nettacker_paths
    for language in glob(os.path.join(nettacker_paths()['home_path'] + '/lib/messages/*.yaml')):
        languages_list.append(language.split('/')[-1].split('.')[0])
    return languages_list


def load_all_modules(limit=-1, full_details=False):
    """
    load all available modules

    limit: return limited number of modules
    full: with full details

    Returns:
        an array of all module names
    """
    # Search for Modules
    from config import nettacker_paths
    if full_details:
        import yaml
    module_names = {}
    for module_name in glob(os.path.join(nettacker_paths()['modules_path'] + '/*/*.yaml')):
        libname = module_name.split('/')[-1].split('.')[0]
        category = module_name.split('/')[-2]
        module_names[libname + '_' + category] = yaml.load(
            StringIO(
                open(
                    nettacker_paths()['modules_path'] +
                    '/' +
                    category +
                    '/' +
                    libname +
                    '.yaml',
                    'r'
                ).read().split('payload:')[0]
            ),
            Loader=yaml.FullLoader
        )['info'] if full_details else None
        if len(module_names) == limit:
            module_names['...'] = {}
            break
    module_names['all'] = {}
    return module_names


def load_all_profiles(limit=-1):
    """
    load all available profiles

    Returns:
        an array of all profile names
    """
    from config import nettacker_paths
    all_modules_with_details = load_all_modules(limit=limit, full_details=True)
    profiles = {}
    if '...' in all_modules_with_details:
        del all_modules_with_details['...']
    del all_modules_with_details['all']
    for key in all_modules_with_details:
        for tag in all_modules_with_details[key]['tags']:
            if tag not in profiles:
                profiles[tag] = []
                profiles[tag].append(key)
            else:
                profiles[tag].append(key)
            if len(profiles) == limit:
                profiles['...'] = []
                profiles['all'] = []
                return profiles
    profiles['all'] = []
    return profiles


def perform_scan(options, target, module_name, scan_unique_id):
    from core.alert import (info,
                            messages)

    socket.socket, socket.getaddrinfo = set_socks_proxy(options.socks_proxy)
    options.target = target
    validate_module = NettackerModules()
    validate_module.module_name = module_name
    validate_module.module_inputs = vars(options)
    validate_module.scan_unique_id = scan_unique_id
    validate_module.target = target
    validate_module.load()
    validate_module.generate_loops()
    info(f"starting scan {target} - {module_name}")
    validate_module.start()
    info(messages("finished_module").format(module_name, target))
    return os.EX_OK
