# frozen_string_literal: true

require_relative "test_helper"

class ReportTest < Minitest::Test
  include Helpers

  def test_two_step_conflict_exact_text
    reg = {
      "foo" => { "1.0.0" => { "bar" => "^1.0" }, "1.1.0" => { "bar" => "^2.0" } },
      "bar" => { "1.0.0" => {}, "1.5.0" => {}, "2.0.0" => { "baz" => "^1" } },
      "baz" => { "1.0.0" => { "foo" => "^1.1" } }
    }
    assert_equal <<~TXT.chomp, explain(reg, { "foo" => "^1.1", "bar" => "^1" })
      Because foo >=1.1.0 depends on bar ^2.0.0 and app depends on foo ^1.1.0, bar ^2.0.0 is required.
      And because app depends on bar ^1.0.0, version solving failed.
    TXT
  end

  def test_no_matching_versions_exact_text
    text = explain({ "foo" => { "1.0.0" => {}, "2.0.0" => {} } }, { "foo" => "^3" })
    assert_equal "Because no versions of foo match ^3.0.0 and app depends on foo ^3.0.0, version solving failed.", text
  end

  def test_missing_package_with_suggestion
    text = explain({ "logsmith" => { "1.0.0" => {} } }, { "logsmth" => "^1" })
    assert_includes text, "does not exist in the registry; did you mean logsmith?"
    assert_includes text, "version solving failed"
  end

  def test_yanked_only_versions_explained
    text = explain({ "a" => { "1.0.0" => { yanked: true } } }, { "a" => "*" })
    assert_includes text, "hidden: 1 yanked"
  end

  def test_prerelease_only_versions_explained
    text = explain({ "a" => { "2.0.0-rc.1" => {} } }, { "a" => "<3" })
    assert_includes text, "hidden: 1 prerelease"
  end

  def test_widened_ranges_in_message
    reg = {
      "web" => { "1.0.0" => { "http" => "^1" }, "1.1.0" => { "http" => "^1" }, "2.0.0" => { "http" => "^2" } },
      "http" => { "1.0.0" => {}, "2.0.0" => {} }
    }
    text = explain(reg, { "web" => "*", "http" => "^3" })
    assert_includes text, "no versions of http match ^3.0.0"
    reg2 = reg.merge("lib" => { "1.0.0" => { "http" => "^1" } })
    text2 = explain(reg2, { "web" => "^2", "lib" => "*" })
    assert_includes text2, "web >=2.0.0 depends on http ^2.0.0"
  end

  def test_root_is_named_by_the_manifest
    man = manifest({ "a" => "^9" }, name: "storefront")
    begin
      Pinion.resolve(man, registry("a" => { "1.0.0" => {} }))
    rescue NoSolution => e
      assert_includes Pinion.explain(e, man), "storefront depends on a ^9.0.0"
    end
  end

  def test_long_lines_wrap_with_indent
    reg = { "a" => { "1.0.0" => { "b" => "^1" } }, "b" => { "1.0.0" => {} } }
    man = manifest({ "a" => "*", "b" => "^2" })
    begin
      Pinion.resolve(man, registry(reg))
    rescue NoSolution => e
      text = Pinion.explain(e, man, width: 40)
      assert text.lines.all? { |l| l.chomp.length <= 60 }
      assert_match(/^  /, text.lines[1])
    end
  end

  # Property: references like "(3)" always point to a numbered line, numbers ascend in reading
  # order, and no internal marker leaks. Checked on every unsatisfiable fuzz registry.
  def test_numbered_references_are_consistent_on_many_proofs
    checked = 0
    (1..250).each do |seed|
      reg, man = Gen.generate(seed, packages: 7, versions: 4, density: 0.3)
      manifest = Manifest.from_hash(man)
      begin
        Pinion.resolve(manifest, Registry.from_hash(reg))
      rescue NoSolution => e
        text = Pinion.explain(e, manifest)
        refute_includes text, "\u0001"
        defined = text.scan(/\((\d+)\)\s*$/).flatten.map(&:to_i)
        assert_equal defined, defined.sort, "seed #{seed}: numbers out of order"
        assert_equal (1..defined.length).to_a, defined, "seed #{seed}: numbering gaps"
        refs = text.scan(/\((\d+)\)/).flatten.map(&:to_i)
        assert_empty refs - defined, "seed #{seed}: dangling reference"
        assert_match(/version solving failed\.\s*\z/, text.gsub(/\s+/, " "))
        checked += 1
      end
    end
    assert_operator checked, :>, 60
  end
end
