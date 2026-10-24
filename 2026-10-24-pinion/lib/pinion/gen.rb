# frozen_string_literal: true

require "json"
require_relative "registry"

module Pinion
  # Random registries/manifests for fuzzing and demos. Fully determined by the seed.
  module Gen
    module_function

    def generate(seed, packages: 6, versions: 4, density: 0.35, extras: true)
      rng = Random.new(seed)
      names = Array.new(packages) { |i| "p#{i}" }
      vers = names.to_h do |n|
        set = {}
        k = 1 + rng.rand(versions)
        major = 1
        minor = 0
        patch = 0
        k.times do
          case rng.rand(5)
          when 0 then major += 1; minor = 0; patch = 0
          when 1, 2 then minor += 1; patch = 0
          else patch += 1
          end
          set[Version.new(major, minor, patch)] = true
        end
        if extras && rng.rand(4).zero?
          set[Version.new(major + 1, 0, 0, ["beta", rng.rand(3).to_s])] = true
        end
        [n, set.keys.sort]
      end
      pk = {}
      names.each do |n|
        pk[n] = {}
        vers[n].each do |v|
          deps = {}
          names.each do |m|
            next if m == n && rng.rand(8).nonzero?
            next unless rng.rand < density
            deps[m] = constraint_for(rng, vers[m])
          end
          entry = { "dependencies" => deps }
          entry["yanked"] = true if extras && rng.rand(12).zero?
          pk[n][v.to_s] = entry
        end
      end
      roots = {}
      (1 + rng.rand(3)).times { m = names[rng.rand(packages)]; roots[m] = constraint_for(rng, vers[m]) }
      manifest = { "name" => "fuzz#{seed}", "dependencies" => roots }
      manifest["allow_prerelease"] = [names[rng.rand(packages)]] if extras && rng.rand(5).zero?
      [{ "packages" => pk }, manifest]
    end

    def constraint_for(rng, vs)
      a = vs[rng.rand(vs.length)]
      b = vs[rng.rand(vs.length)]
      a, b = b, a if b < a
      a = a.base
      b = b.base
      case rng.rand(9)
      when 0 then "^#{a}"
      when 1 then "~#{a}"
      when 2 then ">=#{a}"
      when 3 then "<=#{b}"
      when 4 then "#{a}"
      when 5 then ">=#{a}, <#{b.next_patch.base}"
      when 6 then "!=#{a}"
      when 7 then "^#{a} || ^#{b}"
      else "*"
      end
    end
  end
end
