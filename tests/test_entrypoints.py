from pathlib import Path
import tomllib
import unittest

from buckshot_roulette.cli.main import parse_args as parse_client_args
from buckshot_roulette.server import parse_args as parse_server_args


class EntrypointTests(unittest.TestCase):
    def test_server_args_have_packaged_defaults(self):
        args = parse_server_args([])

        self.assertEqual(args.host, "127.0.0.1")
        self.assertEqual(args.port, 8000)
        self.assertFalse(args.reload)

    def test_server_args_allow_host_port_and_reload(self):
        args = parse_server_args(["--host", "0.0.0.0", "--port", "9000", "--reload"])

        self.assertEqual(args.host, "0.0.0.0")
        self.assertEqual(args.port, 9000)
        self.assertTrue(args.reload)

    def test_client_args_keep_existing_defaults(self):
        args = parse_client_args([])

        self.assertEqual(args.server, "http://127.0.0.1:8000")
        self.assertIsNone(args.name)

    def test_pyproject_exposes_client_and_server_scripts(self):
        pyproject_path = Path(__file__).resolve().parents[1] / "pyproject.toml"
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))

        self.assertEqual(
            data["project"]["scripts"]["buckshot-server"],
            "buckshot_roulette.server:main",
        )
        self.assertEqual(
            data["project"]["scripts"]["buckshot-client"],
            "buckshot_roulette.cli.main:main",
        )


if __name__ == "__main__":
    unittest.main()
