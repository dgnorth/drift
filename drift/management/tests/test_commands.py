# -*- coding: utf-8 -*-

import sys
import unittest
from mock import MagicMock, patch
from drift.management import get_commands, do_execute_cmd
from drift.management.commands import bakeami


def mock_get_service_info():
    ret = MagicMock()
    ret["name"] = "Mock"
    ret["version"] = "0.1.0-mock"
    return ret


def mock_connect_to_region(region):
    ret = MagicMock()
    r = [MagicMock()]
    ret.get_all_images.return_value = r
    return ret

def mock_create_deployment_manifest(*args):
    return "dummy"

def mock_iam_connect_to_region(region):
    ret = MagicMock()
    ret.get_user.return_value = MagicMock()
    return ret

def mock_open(*args):
    return MagicMock()

class NullWriter:
    def write(self, s):
        pass


def suppress_stdout(f):
    with SuppressStdOut():
        return f


class SuppressStdOut:
    def __enter__(self):
        self.old_stdout = sys.stdout
        sys.stdout = NullWriter()

    def __exit__(self, type, value, traceback):
        self.stdout = self.old_stdout


@suppress_stdout
class TestCommands(unittest.TestCase):

    def test_bootstrap(self):
        commands = get_commands()
        self.assertGreater(len(commands), 0)

        with SuppressStdOut():
            with self.assertRaises(SystemExit) as se:
                do_execute_cmd(["-h"])
        self.assertEqual(se.exception.code, 0)

    @patch("boto.ec2.connect_to_region", mock_connect_to_region)
    @patch("boto.iam.connect_to_region", mock_iam_connect_to_region)
    @patch("drift.management.commands.bakeami.get_service_info", mock_get_service_info)
    @patch("drift.management.get_service_info", mock_get_service_info)
    @patch("drift.management.commands.bakeami.checkout", MagicMock)
    @patch("drift.management.commands.bakeami.get_tier_config", MagicMock)
    @patch("drift.management.commands.bakeami.get_tiers_config", MagicMock)
    @patch("drift.management.commands.bakeami.get_tier_name", MagicMock)
    @patch("drift.management.commands.bakeami.create_deployment_manifest", mock_create_deployment_manifest)
    @patch("drift.management.os", MagicMock)
    @patch("drift.management.commands.bakeami.open", mock_open)
    @patch("drift.management.commands.bakeami.os.system", MagicMock)
    @patch("drift.management.commands.bakeami.os.remove", MagicMock)
    @patch("drift.management.commands.bakeami.subprocess.call")
    def test_bakeami(self, mock_call):
        mock_parser = MagicMock()
        bakeami.get_options(mock_parser)

        mock_args = MagicMock()
        mock_args.sourceami = "Bla"
        bakeami.run_command(mock_args)

        mock_args.sourceami = None
        bakeami.run_command(mock_args)

        mock_args.tag = None
        bakeami.run_command(mock_args)

        mock_args.preview = None
        bakeami.run_command(mock_args)

        mock_args.preview = None
        bakeami.run_command(mock_args)

        mock_call.side_effect = Exception
        with self.assertRaises(SystemExit) as se:
            bakeami.run_command(mock_args)
        self.assertEqual(se.exception.code, 1)
