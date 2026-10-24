# frozen_string_literal: true

require_relative "test_helper"

class CliTest < Minitest::Test
  include Helpers

  REG = {
    "packages" => {
      "web" => { "1.0.0" => { "dependencies" => { "http" => "^1" } }, "2.0.0" => { "dependencies" => { "http" => "^2" } } },
      "http" => { "1.0.0" => {}, "1.5.0" => {}, "2.0.0" => {} },
      "json" => { "1.0.0" => { "dependencies" => { "http" => "^1" } } }
    }
  }.freeze
  OK = { "name" => "shop", "dependencies" => { "web" => "^1", "json" => "*" } }.freeze
  BAD = { "name" => "shop", "dependencies" => { "web" => "^2", "json" => "*" } }.freeze

  def run_in(dir, *args) = cli(*args, cwd: dir)

  def test_help_and_version
    code, out, = cli
    assert_equal 0, code
    assert_includes out, "pinion <command>"
    assert_equal [0, "pinion 1.0.0\n"], cli("version")[0, 2]
  end

  def test_unknown_command_and_bad_options_exit_2
    assert_equal 2, cli("bogus")[0]
    assert_match(/unknown command/, cli("bogus")[2])
    with_project(REG, OK) do |d|
      assert_equal 2, run_in(d, "resolve", "--nosuch")[0]
      assert_equal 2, run_in(d, "resolve", "--strategy", "sideways")[0]
    end
  end

  def test_resolve_success
    with_project(REG, OK) do |d|
      code, out, = run_in(d, "resolve")
      assert_equal 0, code
      assert_match(/Resolved 3 packages for shop \(newest\)/, out)
      assert_match(/http\s+1\.5\.0/, out)
      assert_match(/web\s+1\.0\.0/, out)
    end
  end

  def test_resolve_oldest_and_stats
    with_project(REG, OK) do |d|
      _, out, = run_in(d, "resolve", "--strategy", "oldest", "--stats")
      assert_match(/http\s+1\.0\.0/, out)
      assert_match(/decisions: \d+/, out)
    end
  end

  def test_resolve_json
    with_project(REG, OK) do |d|
      code, out, = run_in(d, "resolve", "--json")
      assert_equal 0, code
      j = JSON.parse(out)
      assert_equal true, j["ok"]
      assert_equal "1.5.0", j["packages"]["http"]
      assert_kind_of Integer, j["stats"]["decisions"]
    end
  end

  def test_unsolvable_exit_1_with_explanation_on_stderr
    with_project(REG, BAD) do |d|
      code, out, err = run_in(d, "resolve")
      assert_equal 1, code
      assert_empty out
      assert_match(/no set of versions satisfies shop/, err)
      assert_match(/Because every version of json depends on http \^1\.0\.0 and web >=2\.0\.0 depends on http \^2\.0\.0/, err)
      assert_match(/version solving failed/, err)
    end
  end

  def test_unsolvable_json
    with_project(REG, BAD) do |d|
      code, out, = run_in(d, "resolve", "--json")
      assert_equal 1, code
      j = JSON.parse(out)
      assert_equal false, j["ok"]
      assert_match(/Because/, j["explanation"].first)
    end
  end

  def test_missing_and_malformed_inputs_exit_2_without_traces
    with_project(REG, OK) do |d|
      assert_match(/manifest not found/, run_in(d, "resolve", "nope.json")[2])
      File.write(File.join(d, "bad.json"), "{oops")
      code, _, err = run_in(d, "resolve", "bad.json")
      assert_equal 2, code
      assert_match(/invalid JSON/, err)
      File.write(File.join(d, "m.json"), JSON.generate({ "dependencies" => { "web" => "||" } }))
      assert_match(/empty alternative/, run_in(d, "resolve", "m.json")[2])
      assert_equal 2, run_in(d, "resolve", "--registry", File.join(d, "none.json"))[0]
    end
  end

  def test_lock_verify_flow
    with_project(REG, OK) do |d|
      code, out, = run_in(d, "lock")
      assert_equal 0, code
      assert_match(/wrote pinion.lock \(3 packages\)/, out)
      assert File.file?(File.join(d, "pinion.lock"))
      code, out, = run_in(d, "verify")
      assert_equal 0, code
      assert_match(/lockfile OK/, out)
    end
  end

  def test_verify_fails_after_manifest_edit_and_registry_tamper
    with_project(REG, OK) do |d|
      run_in(d, "lock")
      File.write(File.join(d, "pinion.json"), JSON.generate({ "name" => "shop", "dependencies" => { "web" => "^1" } }))
      code, _, err = run_in(d, "verify")
      assert_equal 1, code
      assert_match(/manifest changed/, err)
      assert_match(/nothing depends on it/, err)
      run_in(d, "lock")
      assert_equal 0, run_in(d, "verify")[0]
      tampered = Marshal.load(Marshal.dump(REG))
      tampered["packages"]["http"]["1.5.0"]["dependencies"] = { "web" => "*" }
      File.write(File.join(d, "registry.json"), JSON.generate(tampered))
      code, out, = run_in(d, "verify", "--json")
      assert_equal 1, code
      assert(JSON.parse(out)["problems"].any? { |p| p.include?("checksum mismatch") })
    end
  end

  def test_lock_preserves_existing_choices_when_registry_grows
    with_project(REG, OK) do |d|
      run_in(d, "lock")
      grown = Marshal.load(Marshal.dump(REG))
      grown["packages"]["http"]["1.9.0"] = {}
      File.write(File.join(d, "registry.json"), JSON.generate(grown))
      _, out, = run_in(d, "resolve")
      assert_match(/http\s+1\.5\.0/, out) # lock preferred
      _, out, = run_in(d, "resolve", "--fresh")
      assert_match(/http\s+1\.9\.0/, out)
      run_in(d, "lock")
      assert_equal "1.5.0", Lockfile.load(File.join(d, "pinion.lock")).versions["http"].to_s
    end
  end

  def test_update_targets_only_named_packages
    with_project(REG, OK) do |d|
      run_in(d, "lock")
      grown = Marshal.load(Marshal.dump(REG))
      grown["packages"]["http"]["1.9.0"] = {}
      grown["packages"]["json"]["1.1.0"] = { "dependencies" => { "http" => "^1" } }
      File.write(File.join(d, "registry.json"), JSON.generate(grown))
      code, out, = run_in(d, "update", "json")
      assert_equal 0, code
      assert_match(/↑ json 1\.0\.0 → 1\.1\.0/, out)
      refute_match(/http/, out) # http stayed locked
      code, out, = run_in(d, "update")
      assert_equal 0, code
      assert_match(/↑ http 1\.5\.0 → 1\.9\.0/, out)
      assert_match(/no changes/, run_in(d, "update")[1])
    end
  end

  def test_update_errors
    with_project(REG, OK) do |d|
      code, _, err = run_in(d, "update")
      assert_equal 2, code
      assert_match(/no lockfile/, err)
      run_in(d, "lock")
      code, _, err = run_in(d, "update", "ghost")
      assert_equal 2, code
      assert_match(/not in the lockfile: ghost/, err)
    end
  end

  def test_update_failure_is_reported_when_no_solution
    with_project(REG, OK) do |d|
      run_in(d, "lock")
      File.write(File.join(d, "pinion.json"), JSON.generate(BAD))
      code, _, err = run_in(d, "update")
      assert_equal 1, code
      assert_match(/version solving failed/, err)
    end
  end

  def test_tree
    with_project(REG, OK) do |d|
      code, out, = run_in(d, "tree")
      assert_equal 0, code
      assert_equal <<~TXT, out
        shop
        ├── json 1.0.0 (any)
        │   └── http 1.5.0 (^1.0.0)
        └── web 1.0.0 (^1.0.0)
            └── http 1.5.0 (^1.0.0) (*)
      TXT
    end
  end

  def test_why
    with_project(REG, OK) do |d|
      code, out, = run_in(d, "why", "http")
      assert_equal 0, code
      assert_match(/http 1\.5\.0 is in the solution because/, out)
      assert_match(/shop → json any → http \^1\.0\.0/, out)
      assert_match(/shop → web \^1\.0\.0 → http \^1\.0\.0/, out)
      assert_match(/combined: \^1\.0\.0/, out)
      assert_match(/Newer versions exist \(2\.0\.0 is newest\)/, out)
      assert_match(/2\.0\.0: json 1\.0\.0 requires \^1\.0\.0; web 1\.0\.0 requires \^1\.0\.0/, out)
      assert_equal 1, run_in(d, "why", "ghost")[0]
      assert_equal 2, run_in(d, "why")[0]
    end
  end

  def test_why_reports_newest_when_nothing_newer
    with_project(REG, OK) do |d|
      _, out, = run_in(d, "why", "web")
      assert_match(/web 1\.0\.0 is in the solution/, out)
      assert_match(/Newer versions exist \(2\.0\.0 is newest\)/, out)
      _, out, = run_in(d, "why", "json")
      assert_match(/1\.0\.0 is the newest available version/, out)
    end
  end

  def test_diff_command
    with_project(REG, OK) do |d|
      run_in(d, "lock")
      old = File.join(d, "old.lock")
      FileUtils.cp(File.join(d, "pinion.lock"), old)
      File.write(File.join(d, "pinion.json"), JSON.generate({ "name" => "shop", "dependencies" => { "web" => "^1" } }))
      run_in(d, "lock")
      code, out, = run_in(d, "diff", old, File.join(d, "pinion.lock"))
      assert_equal 0, code
      assert_match(/- json 1\.0\.0/, out)
      assert_equal 2, run_in(d, "diff", old)[0]
      assert_match(/no changes/, run_in(d, "diff", old, old)[1])
    end
  end

  def test_graph_writes_self_contained_html
    with_project(REG, OK) do |d|
      out_file = File.join(d, "g.html")
      code, out, = run_in(d, "graph", "-o", out_file)
      assert_equal 0, code
      assert_match(/wrote .*g\.html/, out)
      html = File.read(out_file, encoding: "UTF-8")
      assert_includes html, "<svg"
      %w[web http json root].each { |n| assert_includes html, %(data-id="#{n}") }
      assert_includes html, "<title>Pinion — shop</title>"
      refute_match(%r{https?://}, html) # no external assets
      assert_includes html, "prefers-color-scheme"
    end
  end

  def test_graph_escapes_hostile_names
    reg = { "packages" => { "a" => { "1.0.0" => {} } } }
    with_project(reg, { "name" => "<script>alert(1)</script>", "dependencies" => { "a" => "*" } }) do |d|
      run_in(d, "graph", "-o", File.join(d, "g.html"))
      html = File.read(File.join(d, "g.html"), encoding: "UTF-8")
      refute_includes html, "<script>alert(1)</script>"
      assert_includes html, "&lt;script&gt;"
    end
  end

  def test_range_command
    code, out, = cli("range", "^1.2.3 || >=3.0.0 <3.5.0", "1.2.2", "1.9.0", "3.2.0")
    assert_equal 0, code
    assert_match(/1\.2\.2\s+does not match/, out)
    assert_match(/1\.9\.0\s+matches/, out)
    assert_match(/3\.2\.0\s+matches/, out)
    assert_equal 2, cli("range")[0]
    assert_equal 2, cli("range", "||")[0]
  end

  def test_gen_produces_loadable_deterministic_projects
    code, out, = cli("gen", "--seed", "11", "--packages", "5")
    assert_equal 0, code
    j = JSON.parse(out)
    Registry.from_hash(j["registry"])
    Manifest.from_hash(j["manifest"])
    assert_equal out, cli("gen", "--seed", "11", "--packages", "5")[1]
    refute_equal out, cli("gen", "--seed", "12", "--packages", "5")[1]
    Dir.mktmpdir do |d|
      assert_equal 0, cli("gen", "--seed", "4", "-o", d)[0]
      assert_includes cli("resolve", File.join(d, "pinion.json"))[1..2].join, "" # runs end to end (solvable or not)
    end
  end

  def test_fuzz_command
    code, out, = cli("fuzz", "--count", "40", "--packages", "5")
    assert_equal 0, code
    assert_match(/fuzzed 40 registries/, out)
    assert_match(/all agree/, out)
  end

  def test_empty_project
    with_project({ "packages" => {} }, {}) do |d|
      assert_match(/Resolved 0 packages/, run_in(d, "resolve")[1])
      assert_equal 0, run_in(d, "lock")[0]
      assert_equal 0, run_in(d, "verify")[0]
      assert_equal "your project\n", run_in(d, "tree")[1]
    end
  end

  def test_manifest_path_argument_and_custom_registry
    with_project(REG, OK) do |d|
      File.write(File.join(d, "other.json"), JSON.generate({ "name" => "other", "dependencies" => { "http" => "^2" } }))
      FileUtils.cp(File.join(d, "registry.json"), File.join(d, "reg2.json"))
      code, out, = run_in(d, "resolve", "other.json", "--registry", "reg2.json")
      assert_equal 0, code
      assert_match(/http\s+2\.0\.0/, out)
    end
  end

  def test_binary_maps_internal_errors_to_exit_70
    bin = File.expand_path("../bin/pinion", __dir__)
    out = IO.popen([RbConfig.ruby, "-e", "module Pinion; class CLI; def self.run(*) = raise('boom'); end; end; $LOAD_PATH.unshift('#{File.expand_path('../lib', __dir__)}'); require 'pinion/cli'; module Pinion; class CLI; def self.run(*) = raise('boom'); end; end; load '#{bin}'"], err: [:child, :out], &:read)
    assert_match(/internal error: RuntimeError: boom/, out)
    assert_equal 70, $?.exitstatus
  end
end
