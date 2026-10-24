# frozen_string_literal: true

require "json"
require_relative "registry"
require_relative "manifest"

module Pinion
  class LockfileError < StandardError; end

  # pinion.lock: the exact solution plus integrity data, so the same versions can be
  # reproduced and tampering with the registry (or manifest) is detectable.
  class Lockfile
    FORMAT = 1
    Locked = Struct.new(:version, :checksum, :dependencies)

    attr_reader :root, :fingerprint, :packages

    def self.build(manifest, registry, solution)
      pk = solution.to_h do |name, v|
        [name, Locked.new(v, registry.checksum(name, v), registry.entry(name, v).dependencies)]
      end
      new(manifest.name, manifest.fingerprint, pk)
    end

    def self.load(path)
      raise LockfileError, "lockfile not found: #{path}" unless File.file?(path)
      h = JSON.parse(File.read(path))
      raise LockfileError, "#{path}: unsupported lockfile format" unless h.is_a?(Hash) && h["pinion_lock"] == FORMAT
      pk = (h["packages"] || {}).to_h do |n, e|
        [n, Locked.new(Version.parse(e["version"]), e["checksum"], e["dependencies"] || {})]
      end
      new(h["root"], h["manifest"], pk)
    rescue JSON::ParserError => e
      raise LockfileError, "#{path}: invalid JSON (#{e.message.lines.first.strip})"
    rescue ParseError, NoMethodError, TypeError => e
      raise LockfileError, "#{path}: malformed lockfile (#{e.message})"
    end

    def initialize(root, fingerprint, packages)
      @root = root
      @fingerprint = fingerprint
      @packages = packages
    end

    def versions = @packages.to_h { |n, l| [n, l.version] }

    def to_json_text
      JSON.pretty_generate(
        "pinion_lock" => FORMAT,
        "root" => @root,
        "manifest" => @fingerprint,
        "packages" => @packages.sort.to_h { |n, l|
          [n, { "version" => l.version.to_s, "checksum" => l.checksum, "dependencies" => l.dependencies.sort.to_h }]
        }
      ) + "\n"
    end

    def write(path) = File.write(path, to_json_text)

    # Re-derives consistency without running the solver. Returns an array of problem strings.
    def verify(manifest, registry)
      problems = []
      problems << "manifest changed since the lockfile was written (run `pinion lock`)" if manifest.fingerprint != @fingerprint
      vs = versions
      manifest.dependencies.each do |n, set|
        if !vs.key?(n) then problems << "#{n} is required by the manifest but not locked"
        elsif !set.include?(vs[n]) then problems << "locked #{n} #{vs[n]} does not satisfy manifest constraint #{set}"
        end
      end
      @packages.each do |n, l|
        e = registry.entry(n, l.version)
        if e.nil?
          problems << "#{n} #{l.version} no longer exists in the registry"
          next
        end
        problems << "#{n} #{l.version}: registry contents changed (checksum mismatch)" if registry.checksum(n, l.version) != l.checksum
        e.dependencies.each do |dn, dc|
          set = Constraint.parse(dc)
          if !vs.key?(dn) then problems << "#{n} #{l.version} needs #{dn} but it is not locked"
          elsif !set.include?(vs[dn]) then problems << "#{n} #{l.version} requires #{dn} #{set} but #{vs[dn]} is locked"
          end
        end
      end
      reach = reachable(manifest.dependencies.keys)
      (@packages.keys - reach).sort.each { |n| problems << "#{n} is locked but nothing depends on it" }
      problems
    end

    # Non-fatal notices: locked versions that have since been yanked.
    def warnings(registry)
      @packages.filter_map do |n, l|
        e = registry.entry(n, l.version)
        "#{n} #{l.version} has been yanked from the registry (run `pinion update #{n}`)" if e&.yanked
      end
    end

    def reachable(roots)
      seen = {}
      stack = roots.dup
      until stack.empty?
        n = stack.pop
        next if seen[n] || !@packages[n]
        seen[n] = true
        stack.concat(@packages[n].dependencies.keys)
      end
      seen.keys
    end

    # Differences from `other` (older) to self (newer).
    def diff(older)
      a = older.versions
      b = versions
      out = { added: {}, removed: {}, upgraded: {}, downgraded: {} }
      b.each do |n, v|
        if !a.key?(n) then out[:added][n] = v
        elsif v > a[n] then out[:upgraded][n] = [a[n], v]
        elsif v < a[n] then out[:downgraded][n] = [a[n], v]
        end
      end
      a.each { |n, v| out[:removed][n] = v unless b.key?(n) }
      out
    end
  end
end
