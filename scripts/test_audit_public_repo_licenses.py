from pathlib import Path
import json
import os
import subprocess
import tempfile
import textwrap
import unittest


SCRIPT = Path(__file__).with_name("audit_public_repo_licenses.sh")
LICENSE_FILTER = Path(__file__).with_name("public_repo_license_findings.jq")


class PublicRepositoryLicenseAuditTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary_directory.name)
        self.log_path = self.directory / "gh.log"
        mock_gh = self.directory / "gh"
        mock_gh.write_text(
            textwrap.dedent(
                """\
                #!/usr/bin/env python3
                import json
                import os
                from pathlib import Path
                import sys

                arguments = sys.argv[1:]
                log_path = Path(os.environ["MOCK_GH_LOG"])
                with log_path.open("a", encoding="utf-8") as log:
                    print(json.dumps(arguments), file=log)

                if arguments[:2] == ["api", "--paginate"]:
                    endpoint = arguments[2]
                    if endpoint.startswith("/orgs/"):
                        organization = endpoint.split("/")[2]
                        if os.environ.get("MOCK_FAIL_ORG") == organization:
                            raise SystemExit(1)
                        missing = json.loads(os.environ.get("MOCK_MISSING", "{}"))
                        print("\\n".join(missing.get(organization, [])))
                    elif "/issues?" in endpoint:
                        print(os.environ.get("MOCK_ISSUE_NUMBER", ""))
                    else:
                        raise SystemExit(f"Unexpected API endpoint: {endpoint}")
                elif arguments[:2] == ["issue", "create"] or arguments[:2] == ["issue", "edit"]:
                    body_index = arguments.index("--body-file") + 1
                    with log_path.open("a", encoding="utf-8") as log:
                        print(Path(arguments[body_index]).read_text(encoding="utf-8"), file=log)
                elif arguments[:2] in (["issue", "comment"], ["issue", "close"]):
                    pass
                else:
                    raise SystemExit(f"Unexpected gh arguments: {arguments}")
                """
            ),
            encoding="utf-8",
        )
        mock_gh.chmod(0o755)

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def run_audit(self, *arguments: str, **environment: str) -> subprocess.CompletedProcess[str]:
        process_environment = os.environ.copy()
        process_environment.update(
            {
                "PATH": f"{self.directory}:{process_environment['PATH']}",
                "MOCK_GH_LOG": str(self.log_path),
                **environment,
            }
        )
        return subprocess.run(
            [str(SCRIPT), *arguments],
            check=False,
            capture_output=True,
            env=process_environment,
            text=True,
        )

    def read_log(self) -> str:
        return self.log_path.read_text(encoding="utf-8")

    def test_production_filter_selects_only_active_public_license_findings(self) -> None:
        repositories = [
            {
                "full_name": "PickNikRobotics/missing",
                "fork": False,
                "archived": False,
                "license": None,
            },
            {
                "full_name": "PickNikRobotics/unrecognized",
                "fork": False,
                "archived": False,
                "license": {"spdx_id": "NOASSERTION"},
            },
            {
                "full_name": "PickNikRobotics/licensed",
                "fork": False,
                "archived": False,
                "license": {"spdx_id": "BSD-3-Clause"},
            },
            {
                "full_name": "PickNikRobotics/archived",
                "fork": False,
                "archived": True,
                "license": None,
            },
            {
                "full_name": "PickNikRobotics/fork",
                "fork": True,
                "archived": False,
                "license": None,
            },
        ]
        result = subprocess.run(
            ["jq", "-r", "-f", str(LICENSE_FILTER)],
            check=False,
            capture_output=True,
            input=json.dumps(repositories),
            text=True,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(
            result.stdout.splitlines(),
            ["PickNikRobotics/missing", "PickNikRobotics/unrecognized"],
        )

    def test_clean_audit_checks_both_organizations(self) -> None:
        result = self.run_audit("--check-only")
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn("PickNikRobotics PickNikRoboticsServices", result.stdout)
        log = self.read_log()
        self.assertIn("/orgs/PickNikRobotics/repos", log)
        self.assertIn("/orgs/PickNikRoboticsServices/repos", log)
        self.assertIn("NOASSERTION", log)

    def test_missing_license_fails_and_names_repository(self) -> None:
        missing = {"PickNikRoboticsServices": ["PickNikRoboticsServices/example"]}
        result = self.run_audit("--check-only", MOCK_MISSING=json.dumps(missing))
        self.assertEqual(result.returncode, 1)
        self.assertIn("PickNikRoboticsServices/example", result.stdout)

    def test_api_failure_is_not_reported_as_clean(self) -> None:
        result = self.run_audit(
            "--check-only", MOCK_FAIL_ORG="PickNikRoboticsServices"
        )
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unable to audit", result.stderr)
        self.assertNotIn("have a detected root license", result.stdout)

    def test_sort_failure_is_not_reported_as_clean(self) -> None:
        mock_sort = self.directory / "sort"
        mock_sort.write_text("#!/usr/bin/env bash\nexit 1\n", encoding="utf-8")
        mock_sort.chmod(0o755)
        missing = {"PickNikRobotics": ["PickNikRobotics/example"]}
        result = self.run_audit("--check-only", MOCK_MISSING=json.dumps(missing))
        self.assertEqual(result.returncode, 2)
        self.assertIn("Unable to sort", result.stderr)
        self.assertNotIn("have a detected root license", result.stdout)

    def test_update_mode_creates_one_tracking_issue(self) -> None:
        missing = {"PickNikRobotics": ["PickNikRobotics/example"]}
        result = self.run_audit("--update-issue", MOCK_MISSING=json.dumps(missing))
        self.assertEqual(result.returncode, 1)
        log = self.read_log()
        self.assertIn('["issue", "create"', log)
        self.assertIn("[written by AI]", log)
        self.assertIn("- [ ] [PickNikRobotics/example]", log)
        self.assertIn("machine-owned body is replaced on every run", log)
        self.assertIn("record review notes and dispositions in issue comments", log)

    def test_update_mode_closes_existing_issue_after_remediation(self) -> None:
        result = self.run_audit("--update-issue", MOCK_ISSUE_NUMBER="42")
        self.assertEqual(result.returncode, 0, result.stderr)
        log = self.read_log()
        self.assertIn('["issue", "comment", "42"', log)
        self.assertIn('["issue", "close", "42"', log)

    def test_update_mode_fails_on_duplicate_tracking_issues(self) -> None:
        result = self.run_audit("--update-issue", MOCK_ISSUE_NUMBER="42\n43")
        self.assertEqual(result.returncode, 2)
        self.assertIn("multiple open tracking issues", result.stderr)


if __name__ == "__main__":
    unittest.main()
