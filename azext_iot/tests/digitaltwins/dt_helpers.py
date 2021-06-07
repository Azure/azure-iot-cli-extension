# coding=utf-8
# --------------------------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for license information.
# --------------------------------------------------------------------------------------------

import urllib
import json
from azext_iot.tests.generators import generate_generic_id

etag = 'AAAA=='
resource_group = 'myrg'


def generate_model_id():
    normal_id = "dtmi:com:{}:{};1".format(generate_generic_id(), generate_generic_id())
    url_id = urllib.parse.quote_plus(normal_id)
    return normal_id, url_id


generic_result = json.dumps({"result": generate_generic_id()})
model_id, url_model_id = generate_model_id()
twin_id = generate_generic_id()


def generate_model_result(model_id=None):
    model_id = model_id if model_id else generate_model_id()[0]
    return {
        "model": {
            "@context" : ["dtmi:com:context;2"],
            "@id" : model_id,
            "@type" : "Interface"
        },
        "id": model_id
    }


def generate_relationship(relationship_name=None):
    return {
        "$relationshipId": generate_generic_id(),
        "$relationshipName": relationship_name,
        "$sourceId": generate_generic_id()
    }


def generate_twin_result(randomized=False):
    return {
        "$dtId": generate_generic_id() if randomized else twin_id,
        "$etag": generate_generic_id() if randomized else etag,
        "$metadata": {
            "$model": generate_generic_id() if randomized else model_id
        }
    }
