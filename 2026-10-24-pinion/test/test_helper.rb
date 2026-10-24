# frozen_string_literal: true

$LOAD_PATH.unshift File.expand_path("../lib", __dir__)
require "minitest/autorun"
require "stringio"
require "tmpdir"
require "json"
require "pinion/cli"
require "pinion/fuzz"

module Helpers
  include Pinion

  def v(s) = Version.parse(s)
  def c(s) = Constraint.parse(s)

  # reg: { "pkg" => { "1.0.0" => { "dep" => "^1" } } }  (a version may map to nil, or to :yanked => ...)
  def registry(reg)
    pk = reg.to_h do |name, versions|
      [name, versions.to_h do |ver, deps|
        yanked = deps.is_a?(Hash) && deps.delete(:yanked)
        e = { "dependencies" => deps || {} }
        e["yanked"] = true if yanked
        [ver, e]
      end]
    end
    Registry.from_hash({ "packages" => pk })
  end

  def manifest(deps, name: "app", **extra)
    Manifest.from_hash({ "name" => name, "dependencies" => deps }.merge(extra.transform_keys(&:to_s)))
  end

  def solve(reg, deps, **opts)
    man = deps.is_a?(Manifest) ? deps : manifest(deps)
    Pinion.resolve(man, reg.is_a?(Registry) ? reg : registry(reg), **opts).solution.transform_values(&:to_s)
  end

  def explain(reg, deps, **opts)
    man = manifest(deps)
    Pinion.resolve(man, registry(reg), **opts)
    flunk "expected no solution"
  rescue NoSolution => e
    Pinion.explain(e, man, width: 10_000)
  end

  def cli(*args, cwd: Dir.pwd)
    out = StringIO.new
    err = StringIO.new
    code = Pinion::CLI.run(args, out: out, err: err, cwd: cwd)
    [code, out.string, err.string]
  end

  def with_project(registry_hash, manifest_hash)
    Dir.mktmpdir("pinion") do |dir|
      File.write(File.join(dir, "registry.json"), JSON.generate(registry_hash))
      File.write(File.join(dir, "pinion.json"), JSON.generate(manifest_hash))
      yield dir
    end
  end
end
