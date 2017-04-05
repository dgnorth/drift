# -*- coding: utf-8 -*-

from drift.core.extensions.jwt import current_user
from drift.utils import get_config


def get_provider_config(provider_name):
    conf = get_config()
    row = conf.table_store.get_table('platforms').find({'product_name': conf.product['product_name'],
                                                        'provider_name': provider_name})
    return row[0]['provider_details']
