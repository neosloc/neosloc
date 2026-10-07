"""Swift support and the desktop GUI surface."""
import os
import shutil
import tempfile
import textwrap
import unittest

from neosloc.assess import assess
from neosloc.cli import analyze
from neosloc.facts import Facts
from neosloc.ladder import detect_surfaces
from neosloc.repo import Repo

PACKAGE_CLI = textwrap.dedent("""\
    // swift-tools-version:5.9
    import PackageDescription

    let package = Package(
        name: "geotool",
        products: [
            .executable(name: "geotool", targets: ["GeoTool"]),
            .library(name: "GeoKit", targets: ["GeoKit"]),
        ],
        dependencies: [
            .package(url: "https://github.com/apple/swift-argument-parser", from: "1.3.0"),
        ],
        targets: [
            .executableTarget(name: "GeoTool", dependencies: ["GeoKit"]),
            .target(name: "GeoKit"),
            .testTarget(name: "GeoKitTests", dependencies: ["GeoKit"]),
        ]
    )
""")

MAIN = textwrap.dedent("""\
    import ArgumentParser
    import GeoKit

    @main
    struct GeoTool: ParsableCommand {
        @Flag(help: "Print JSON.") var json = false
        @Argument(help: "Input file.") var input: String

        func run() throws {
            do {
                print(try GeoKit.parse(input))
            } catch {
                FileHandle.standardError.write("error\\n".data(using: .utf8)!)
                throw ExitCode.failure
            }
        }
    }
""")

LIB = textwrap.dedent("""\
    import Logging

    public enum GeoError: Error {
        case malformed(String)
    }

    public struct GeoKit {
        static let log = Logger(label: "geokit")

        /// Parses a file and logs at debug level.
        @available(*, deprecated, renamed: "load")
        public static func parse(_ path: String) throws -> String {
            log.debug("parsing")
            log.error("failed")
            return path
        }
    }
""")


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.dir)

    def write(self, rel, text):
        path = os.path.join(self.dir, rel)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(text)

    def kinds(self):
        return detect_surfaces(Facts(Repo(self.dir))).kinds

    def dims(self):
        return {d.key: d for d in assess(Repo(self.dir))[0]}

    def level(self, key, surface):
        return self.dims()[key].surfaces[surface]["level"]

    def first_missing(self, key, surface):
        return self.dims()[key].surfaces[surface]["first_missing"]


class Swift(Fixture):
    def swift_package(self):
        self.write("Package.swift", PACKAGE_CLI)
        self.write("Sources/GeoTool/main.swift", MAIN)
        self.write("Sources/GeoKit/GeoKit.swift", LIB)
        self.write("Tests/GeoKitTests/GeoKitTests.swift", "import XCTest\nfinal class GeoKitTests: XCTestCase {}\n")

    def test_package_is_cli_and_library(self):
        self.swift_package()
        self.assertEqual(self.kinds(), ["cli", "library"])

    def test_tests_and_manifest_are_recognised(self):
        self.swift_package()
        repo = Repo(self.dir)
        self.assertTrue(repo.is_test("Tests/GeoKitTests/GeoKitTests.swift"))
        self.assertIn("Package.swift", repo.manifests())
        leg = Facts(repo).legibility()
        self.assertEqual(leg["test_files"], 1)
        self.assertEqual(leg["typed_ratio"], 1.0)  # Swift is statically typed

    def test_cli_ladder(self):
        self.swift_package()
        self.assertEqual(self.first_missing("interface", "cli"), "machine-output")  # --json, but exit codes undocumented
        self.write("README.md", "# geotool\n\nExit status: 0 ok, 1 malformed input, 2 usage.\n")
        self.assertEqual(self.level("interface", "cli"), 3)
        self.assertGreaterEqual(self.level("ergonomics", "cli"), 2)  # stderr + ExitCode

    def test_library_ladder_and_logging(self):
        self.swift_package()
        self.assertEqual(self.level("interface", "library"), 3)  # public access control, statically typed
        self.write("Sources/GeoKit/GeoKit.docc/GeoKit.md", "# ``GeoKit``\n")
        self.assertEqual(self.level("interface", "library"), 4)  # DocC
        obs = self.dims()["observability"].surfaces["library"]
        self.assertGreaterEqual(obs["level"], 2)                  # swift-log Logger, two levels
        self.assertEqual(self.level("ergonomics", "library"), 1)  # Error types, no exits

    def test_deprecation_and_tag_publishing(self):
        import subprocess
        self.swift_package()
        self.write("CHANGELOG.md", "## 1.0.0\n\n- Breaking: renamed parse.\n")
        subprocess.run(["git", "-C", self.dir, "init", "-q"], check=True)
        subprocess.run(["git", "-C", self.dir, "add", "-A"], check=True)
        subprocess.run(["git", "-C", self.dir, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-qm", "x"], check=True)
        subprocess.run(["git", "-C", self.dir, "tag", "1.0.0"], check=True)
        self.assertGreaterEqual(self.dims()["stability"].level, 3)  # @available(*, deprecated)
        published = next(r for r in self.dims()["embeddability"].surfaces["library"]["requirements"]
                         if r["id"] == "published-minimal")
        self.assertTrue(published["met"])  # SwiftPM resolves packages by semver tag

    def test_vapor_service(self):
        self.write("Package.swift", '// swift-tools-version:5.9\nimport PackageDescription\nlet package = Package(name: "api")\n')
        self.write("Sources/App/routes.swift", 'import Vapor\n\nfunc routes(_ app: Application) throws {\n'
                   '    app.get("health") { _ in "ok" }\n    app.post("items") { req in "" }\n}\n')
        self.assertIn("service", self.kinds())
        self.assertEqual(Facts(Repo(self.dir)).route_total(), 2)

    def test_code_view_multiline_prose_and_regex(self):
        from neosloc.codeview import code_view
        src = ('let help = """\nThis exports the data so you can import it later.\n"""\n'
               'let rx = try NSRegularExpression(pattern: "webhook")\nlet h = ["Idempotency-Key": k]\n')
        v = code_view(src, "swift")
        self.assertNotIn("exports the data", v)
        self.assertNotIn("webhook", v)
        self.assertIn('"Idempotency-Key"', v)


class Desktop(Fixture):
    def electron_app(self):
        self.write("package.json", '{"name": "notes", "private": true, "main": "main.js",'
                   ' "devDependencies": {"electron": "31", "electron-builder": "24"}}')
        self.write("index.html", "<html></html>")
        self.write("main.js", "const { app, ipcMain } = require('electron')\nipcMain.handle('save', () => 1)\n")

    def test_toolkits(self):
        cases = {
            "electron": lambda: self.electron_app(),
            "tauri": lambda: self.write("src-tauri/tauri.conf.json", "{}"),
            "qt": lambda: self.write("app.py", "from PySide6.QtWidgets import QApplication\napp = QApplication([])\n"),
            "tkinter": lambda: self.write("app.py", "import tkinter as tk\nroot = tk.Tk()\n"),
            "wpf": lambda: self.write("App.csproj", "<Project><PropertyGroup><UseWPF>true</UseWPF></PropertyGroup></Project>"),
            "macos": lambda: self.write("App/App.swift", "import SwiftUI\nimport AppKit\n@main struct A: App {}\n"),
        }
        for name, make in cases.items():
            shutil.rmtree(self.dir)
            os.makedirs(self.dir)
            make()
            self.assertIn("desktop", self.kinds(), name)

    def test_electron_is_not_also_a_frontend(self):
        self.electron_app()
        self.assertEqual(self.kinds(), ["desktop"])

    def test_ios_swiftui_is_not_desktop(self):
        self.write("App/App.swift", "import SwiftUI\n@main struct A: App { var body: some Scene { WindowGroup {} } }\n")
        self.assertNotIn("desktop", self.kinds())

    def test_internal_ipc_is_not_automation(self):
        self.electron_app()
        self.assertEqual(self.level("interface", "desktop"), 0)

    def test_interface_ladder(self):
        self.electron_app()
        self.write("main.js", "const { app } = require('electron')\napp.setAsDefaultProtocolClient('notes')\n"
                   "const args = process.argv\n")
        self.assertEqual(self.level("interface", "desktop"), 1)
        self.write("dbus.js", "const dbus = require('dbus-next')\n")
        self.assertEqual(self.level("interface", "desktop"), 2)
        self.write("cli.js", "if (process.argv.includes('--headless')) { run() }\n")
        self.assertEqual(self.level("interface", "desktop"), 3)
        self.write("org.notes.App.DBus.xml", "<node><interface name='org.notes.App'/></node>")
        self.assertEqual(self.level("interface", "desktop"), 4)

    def test_embeddability_ladder(self):
        self.electron_app()
        self.write("README.md", "Build:\n\n```\nnpm run dist\n```\n")
        self.assertEqual(self.level("embeddability", "desktop"), 2)  # electron-builder
        self.write(".github/workflows/release.yml", "steps:\n  - run: npx electron-builder --publish always\n")
        self.assertEqual(self.level("embeddability", "desktop"), 3)
        self.write("docs/admin.md", "Set the server with `defaults write org.notes server https://x`.\n")
        self.assertEqual(self.level("embeddability", "desktop"), 4)

    def test_ergonomics_needs_headless(self):
        self.electron_app()
        self.assertEqual(self.first_missing("ergonomics", "desktop"), "headless-failures")
        note = next(r["note"] for r in self.dims()["ergonomics"].surfaces["desktop"]["requirements"] if r["level"] == 1)
        self.assertIn("headless", note)

    def test_identity_with_credential_store(self):
        self.write("src-tauri/tauri.conf.json", "{}")
        self.assertIsNone(self.dims()["identity"].level)
        self.write("src-tauri/Cargo.toml", '[package]\nname = "x"\n[dependencies]\nkeyring = "3"\n')
        self.assertEqual(self.level("identity", "desktop"), 1)

    def test_observability(self):
        self.electron_app()
        self.write("log.js", "const log = require('electron-log')\nconst level = { logLevel: 'debug' }\n"
                   "require('@sentry/electron').init({})\n")
        self.assertEqual(self.level("observability", "desktop"), 3)

    def test_ui_products_are_adopted_in_minutes(self):
        self.electron_app()
        mb = analyze(self.dir).make_or_buy
        self.assertEqual(mb["buy"]["via"]["use"], "desktop UI")
        self.assertLessEqual(mb["buy"]["adoption_minutes"]["first_use"], 5)


if __name__ == "__main__":
    unittest.main()
