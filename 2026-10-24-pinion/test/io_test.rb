# frozen_string_literal: true

require_relative "test_helper"

class RegistryManifestTest < Minitest::Test
  include Helpers

  def test_registry_validation_errors
    bad = [
      [{ "pkgs" => {} }, /missing "packages"/],
      [[], /top level must be an object/],
      [{ "packages" => { "bad name" => {} } }, /invalid package name/],
      [{ "packages" => { "a" => [] } }, /must map versions/],
      [{ "packages" => { "a" => { "1.0" => {} } } }, /invalid version/],
      [{ "packages" => { "a" => { "1.0.0" => 5 } } }, /entry must be an object/],
      [{ "packages" => { "a" => { "1.0.0" => { "dependencies" => [] } } } }, /dependencies must be an object/],
      [{ "packages" => { "a" => { "1.0.0" => { "dependencies" => { "b" => 1 } } } } }, /must be a string/],
      [{ "packages" => { "a" => { "1.0.0" => { "dependencies" => { "b" => "^^" } } } } }, /dependency b/],
      [{ "packages" => { "a" => { "1.0.0+x" => {}, "1.0.0+y" => {} } } }, /duplicate version/],
    ]
    bad.each { |h, re| assert_raises(RegistryError, h.inspect) { Registry.from_hash(h) }.message.then { |m| assert_match re, m } }
  end

  def test_registry_loads_from_file_and_reports_bad_json
    Dir.mktmpdir do |d|
      f = File.join(d, "r.json")
      File.write(f, '{"packages":{"a":{"1.0.0":{}}}}')
      assert_equal %w[a], Registry.load(f).names
      File.write(f, "{nope")
      assert_match(/invalid JSON/, assert_raises(RegistryError) { Registry.load(f) }.message)
      assert_match(/not found/, assert_raises(RegistryError) { Registry.load(File.join(d, "x")) }.message)
    end
  end

  def test_registry_checksum_depends_on_dependencies_and_version
    r1 = registry("a" => { "1.0.0" => { "b" => "^1" } })
    r2 = registry("a" => { "1.0.0" => { "b" => "^2" } })
    r3 = registry("a" => { "1.0.1" => { "b" => "^1" } })
    refute_equal r1.checksum("a", v("1.0.0")), r2.checksum("a", v("1.0.0"))
    refute_equal r1.checksum("a", v("1.0.0")), r3.checksum("a", v("1.0.1"))
    assert_nil r1.checksum("zz", v("1.0.0"))
  end

  def test_registry_to_h_round_trips
    r = registry("a" => { "1.0.0" => { "b" => "^1" }, "1.1.0" => { yanked: true } }, "b" => { "1.0.0" => {} })
    again = Registry.from_hash(r.to_h)
    assert_equal r.to_h, again.to_h
    assert again.entry("a", v("1.1.0")).yanked
  end

  def test_manifest_validation
    assert_raises(ManifestError) { Manifest.from_hash([]) }
    assert_raises(ManifestError) { Manifest.from_hash({ "name" => 5 }) }
    assert_raises(ManifestError) { Manifest.from_hash({ "dependencies" => [] }) }
    assert_raises(ManifestError) { Manifest.from_hash({ "dependencies" => { "a" => 1 } }) }
    assert_raises(ManifestError) { Manifest.from_hash({ "dependencies" => { "a" => "||" } }) }
    assert_raises(ManifestError) { Manifest.from_hash({ "allow_prerelease" => "yes" }) }
    assert_equal "your project", Manifest.from_hash({}).name
  end

  def test_manifest_prerelease_range_implies_opt_in
    m = Manifest.from_hash({ "dependencies" => { "a" => ">=1.0.0-rc.1", "b" => "^1" }, "allow_prerelease" => ["z"] })
    assert_equal %w[a z], m.allow_prerelease
  end

  def test_manifest_fingerprint_tracks_requirements
    a = manifest({ "x" => "^1" })
    b = manifest({ "x" => "^1" }, name: "other-name")
    c = manifest({ "x" => "^2" })
    assert_equal a.fingerprint, b.fingerprint
    refute_equal a.fingerprint, c.fingerprint
  end
end

class LockfileTest < Minitest::Test
  include Helpers

  REG = { "a" => { "1.0.0" => { "b" => "^1" }, "1.1.0" => { "b" => "^1" } }, "b" => { "1.0.0" => {}, "1.2.0" => {} } }.freeze

  def build(reg = REG, deps = { "a" => "*" })
    man = manifest(deps)
    registry = registry(reg.transform_values(&:dup))
    sol = Pinion.resolve(man, registry).solution
    [man, registry, Lockfile.build(man, registry, sol)]
  end

  def test_build_write_load_round_trip
    _, _, lock = build
    Dir.mktmpdir do |d|
      f = File.join(d, "pinion.lock")
      lock.write(f)
      again = Lockfile.load(f)
      assert_equal lock.versions, again.versions
      assert_equal lock.to_json_text, again.to_json_text
      assert_equal({ "a" => "1.1.0", "b" => "1.2.0" }, again.versions.transform_values(&:to_s))
    end
  end

  def test_verify_clean
    man, reg, lock = build
    assert_empty lock.verify(man, reg)
  end

  def test_verify_detects_manifest_edit
    _, reg, lock = build
    problems = lock.verify(manifest({ "a" => "^1", "b" => "^1" }), reg)
    assert(problems.any? { |p| p.include?("manifest changed") })
    assert(problems.empty? == false)
  end

  def test_verify_detects_manifest_constraint_violation
    _, reg, lock = build
    problems = lock.verify(manifest({ "a" => "<1.1.0" }), reg)
    assert(problems.any? { |p| p.include?("does not satisfy manifest constraint") })
  end

  def test_verify_detects_registry_tampering
    man, _, lock = build
    tampered = registry("a" => { "1.0.0" => { "b" => "^1" }, "1.1.0" => { "b" => "^1", "evil" => "*" } }, "b" => { "1.0.0" => {}, "1.2.0" => {} }, "evil" => { "1.0.0" => {} })
    problems = lock.verify(man, tampered)
    assert(problems.any? { |p| p.include?("checksum mismatch") })
    assert(problems.any? { |p| p.include?("needs evil but it is not locked") })
  end

  def test_verify_detects_removed_version
    man, _, lock = build
    problems = lock.verify(man, registry("a" => { "1.0.0" => { "b" => "^1" } }, "b" => { "1.2.0" => {} }))
    assert(problems.any? { |p| p.include?("no longer exists") })
  end

  def test_verify_detects_hand_edited_version
    man, reg, lock = build
    edited = Lockfile.new(lock.root, lock.fingerprint, lock.packages.merge("b" => Lockfile::Locked.new(v("1.0.0"), lock.packages["b"].checksum, {})))
    problems = edited.verify(man, reg)
    assert(problems.any? { |p| p.include?("checksum mismatch") })
  end

  def test_verify_detects_orphans
    man, reg, lock = build
    orphan = Lockfile::Locked.new(v("1.0.0"), reg.checksum("b", v("1.0.0")), {})
    extra = Lockfile.new(lock.root, lock.fingerprint, lock.packages.merge("zz" => orphan))
    assert(extra.verify(man, reg).any? { |p| p.include?("nothing depends on it") })
  end

  def test_load_rejects_garbage
    Dir.mktmpdir do |d|
      f = File.join(d, "l")
      ["{nope", "[]", '{"pinion_lock":2}', '{"pinion_lock":1,"packages":{"a":{"version":"x"}}}', '{"pinion_lock":1,"packages":[]}'].each do |txt|
        File.write(f, txt)
        assert_raises(LockfileError, txt) { Lockfile.load(f) }
      end
      assert_raises(LockfileError) { Lockfile.load(File.join(d, "missing")) }
    end
  end

  def test_diff
    _, _, old = build
    reg2 = { "a" => { "1.0.0" => { "b" => "^1" }, "2.0.0" => { "c" => "*" } }, "b" => { "1.0.0" => {}, "1.2.0" => {} }, "c" => { "1.0.0" => {} } }
    man2 = manifest({ "a" => "^2" })
    r2 = registry(reg2)
    new = Lockfile.build(man2, r2, Pinion.resolve(man2, r2).solution)
    d = new.diff(old)
    assert_equal({ "c" => v("1.0.0") }, d[:added])
    assert_equal({ "b" => v("1.2.0") }, d[:removed])
    assert_equal({ "a" => [v("1.1.0"), v("2.0.0")] }, d[:upgraded])
    assert_empty d[:downgraded]
    assert_equal({ "a" => [v("2.0.0"), v("1.1.0")] }, old.diff(new)[:downgraded])
  end

  def test_yanked_warning
    man, _, lock = build
    reg = registry("a" => { "1.0.0" => { "b" => "^1" }, "1.1.0" => { "b" => "^1", yanked: true } }, "b" => { "1.0.0" => {}, "1.2.0" => {} })
    assert_equal ["a 1.1.0 has been yanked from the registry (run `pinion update a`)"], lock.warnings(reg)
    assert_empty lock.verify(man, reg).reject { |p| p.include?("checksum") }
  end
end
