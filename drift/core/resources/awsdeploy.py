# -*- coding: utf-8 -*-
from __future__ import absolute_import

import logging
log = logging.getLogger(__name__)


# defaults when making a new tier
TIER_DEFAULTS = {
    "region": "<PLEASE FILL IN>",
    "ssh_key": "<PLEASE FILL IN>",
}


def register_resource_on_tier(ts, tier, attributes):
    """
    Tier registration callback.
    'tier' is from table 'tiers'.
    'attributes' is a dict containing optional attributes for default values.
    """
    # LEGACY SUPPORT! Copy the 'attributes' to the root as 'aws':
    tier['aws'] = attributes
