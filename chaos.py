#!/usr/bin/env python

import logging
import kubernetes
import math
import os
import random
import time
import pytz
import json
import datetime

from kubernetes.client.rest import ApiException

LOGGER = logging.getLogger(__name__)

logging.basicConfig(level=logging.INFO)

KILL_INTERVAL = float(os.environ.get('CHAOS_PONY_INTERVAL_SECONDS', 300))
NUM_KILLS = float(os.environ.get('CHAOS_PONY_KILLS_PER_INTERVAL', 2))
# No error handling, if things go wrong Kubernetes will restart for us!


def kill_pod(pod):
    LOGGER.info("Terminating pod %s/%s", pod.metadata.namespace, pod.metadata.name)
    event_name = "Chaos pony kill pod %s" % pod.metadata.name
    v1.delete_namespaced_pod(
        name=pod.metadata.name,
        namespace=pod.metadata.namespace,
        body=kubernetes.client.V1DeleteOptions(),
    )
    event_timestamp = datetime.datetime.now(pytz.utc)
    try:
        event = v1.read_namespaced_event(event_name, namespace=pod.metadata.namespace)
        event.count += 1
        event.last_timestamp = event_timestamp
        v1.replace_namespaced_event(event_name, pod.metadata.namespace, event)
    except ApiException as e:
        error_data = json.loads(e.body)
        error_code = int(error_data['code'])
        if error_code == 404:
            new_event = kubernetes.client.V1Event(
                count=1,
                first_timestamp=event_timestamp,
                involved_object=kubernetes.client.V1ObjectReference(
                    kind="Pod",
                    name=pod.metadata.name,
                    namespace=pod.metadata.namespace,
                    uid=pod.metadata.uid,
                ),
                last_timestamp=event_timestamp,
                message="Pod deleted by chaos monkey",
                metadata=kubernetes.client.V1ObjectMeta(
                    name=event_name,
                ),
                reason="ChaosMonkeyDelete",
                source=kubernetes.client.V1EventSource(
                    component="chaos-monkey",
                ),
                type="Warning",
            )
            v1.create_namespaced_event(namespace=pod.metadata.namespace, body=new_event)
        else:
            raise


def random_poisson(y):
    # https://en.wikipedia.org/wiki/Poisson_distribution#Generating_Poisson-distributed_random_variables
    x = 0.0
    p = math.exp(-y)
    s = p
    u = random.random()
    while u > s:
        x += 1.0
        p *= y / x
        s += p
    return x


try:
    kubernetes.config.load_incluster_config()
except kubernetes.config.config_exception.ConfigException:
    kubernetes.config.load_kube_config()
v1 = kubernetes.client.CoreV1Api()

while True:
    interval = random.expovariate(1.0 / KILL_INTERVAL)
    y = NUM_KILLS * interval / KILL_INTERVAL
    num_kills = int(random_poisson(y))
    LOGGER.info("Sleeping %d seconds then killing %d pods",
                interval, num_kills)
    time.sleep(interval)

    pods = v1.list_pod_for_all_namespaces().items
    pods_to_kill = random.sample(pods, num_kills)
    for pod in pods_to_kill:
        kill_pod(pod)
