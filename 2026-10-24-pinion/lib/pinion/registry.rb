# frozen_string_literal: true

require "json"
require "digest"
require_relative "constraint"

module Pinion
  class RegistryError < StandardError; end

  # Raw package index: name -> version -> {dependencies, yanked}. Everything is parsed
  # and validated eagerly so a malformed entry is reported with its location.
  class Registry
    Entry = Struct.new(:version, :dependencies, :yanked) # dependencies: name => constraint String

    attr_reader :packages

    def self.load(path)
      raise RegistryError, "registry file not found: #{path}" unless File.file?(path)
      from_hash(JSON.parse(File.read(path)), source: path)
    rescue JSON::ParserError => e
      raise RegistryError, "#{path}: invalid JSON (#{e.message.lines.first.strip})"
    end

    def self.from_hash(h, source: "registry")
      raise RegistryError, "#{source}: top level must be an object" unless h.is_a?(Hash)
      pk = h["packages"]
      raise RegistryError, "#{source}: missing \"packages\" object" unless pk.is_a?(Hash)
      new(pk, source)
    end

    def initialize(pk, source = "registry")
      @packages = {}
      pk.each do |name, versions|
        raise RegistryError, "#{source}: invalid package name #{name.inspect}" unless name.is_a?(String) && name.match?(/\A[A-Za-z0-9][A-Za-z0-9._-]*\z/)
        raise RegistryError, "#{source}: package #{name} must map versions to entries" unless versions.is_a?(Hash)
        @packages[name] = {}
        versions.each do |vs, body|
          v = begin
            Version.parse(vs)
          rescue ParseError => e
            raise RegistryError, "#{source}: #{name}: #{e.message}"
          end
          body ||= {}
          raise RegistryError, "#{source}: #{name} #{vs}: entry must be an object" unless body.is_a?(Hash)
          deps = body["dependencies"] || {}
          raise RegistryError, "#{source}: #{name} #{vs}: dependencies must be an object" unless deps.is_a?(Hash)
          deps.each do |dn, dc|
            raise RegistryError, "#{source}: #{name} #{vs}: constraint for #{dn} must be a string" unless dc.is_a?(String)
            begin
              Constraint.parse(dc)
            rescue ParseError => e
              raise RegistryError, "#{source}: #{name} #{vs}: dependency #{dn}: #{e.message}"
            end
          end
          raise RegistryError, "#{source}: duplicate version #{name} #{v}" if @packages[name].key?(v)
          @packages[name][v] = Entry.new(v, deps.dup.freeze, body["yanked"] == true)
        end
      end
    end

    def names = @packages.keys.sort
    def known?(name) = @packages.key?(name)
    def versions(name) = (@packages[name] || {}).keys.sort
    def entry(name, version) = @packages.dig(name, version)

    # Stable fingerprint of what a lockfile entry depends on: the version and its dependency list.
    def checksum(name, version)
      e = entry(name, version) or return nil
      body = e.dependencies.sort.map { |k, c| "#{k} #{c}" }.join("\n")
      Digest::SHA256.hexdigest("#{name}@#{version}\n#{body}")
    end

    def to_h
      { "packages" => @packages.sort.to_h { |n, vs|
        [n, vs.sort.to_h { |v, e|
          h = { "dependencies" => e.dependencies.sort.to_h }
          h["yanked"] = true if e.yanked
          [v.to_s, h]
        }]
      } }
    end
  end

  # The view of a registry the solver sees after applying policy:
  #  * yanked versions are hidden unless already locked
  #  * prereleases are hidden unless allowed globally, per package, or already locked
  class Universe
    def initialize(registry, allow_prerelease: [], locked: {})
      @registry = registry
      @allow_all = allow_prerelease == true
      @allow = allow_prerelease.is_a?(Array) ? allow_prerelease : []
      @locked = locked
      @versions = {}
      @deps = {}
    end

    attr_reader :registry

    def known?(pkg) = @registry.known?(pkg)

    def versions(pkg)
      @versions[pkg] ||= @registry.versions(pkg).select { |v| visible?(pkg, v) }.freeze
    end

    def deps(pkg, version)
      @deps[[pkg, version]] ||= @registry.entry(pkg, version).dependencies.to_h { |n, c| [n, Constraint.parse(c)] }.freeze
    end

    def allow_prerelease_for?(pkg) = @allow_all || @allow.include?(pkg)

    # Why nothing in `set` is installable for pkg (nil when the plain "no versions match" is the whole story).
    def empty_reason(pkg, set)
      unless known?(pkg)
        near = @registry.names.select { |n| edit_distance(n.downcase, pkg.downcase) <= [2, pkg.length / 4].max }.first(3)
        return "it does not exist in the registry#{near.empty? ? '' : "; did you mean #{near.join(' or ')}?"}"
      end
      hidden = @registry.versions(pkg).select { |v| set.include?(v) && !visible?(pkg, v) }
      return nil if hidden.empty?
      yanked = hidden.count { |v| @registry.entry(pkg, v).yanked }
      pre = hidden.count(&:prerelease?)
      bits = []
      bits << "#{yanked} yanked" if yanked.positive?
      bits << "#{pre} prerelease" if pre.positive? && pre != yanked
      "#{hidden.length} matching #{hidden.length == 1 ? 'version is' : 'versions are'} hidden: #{bits.join(', ')}"
    end

    private

    def edit_distance(a, b)
      prev = (0..b.length).to_a
      a.each_char.with_index(1) do |ca, i|
        cur = [i]
        b.each_char.with_index(1) { |cb, j| cur << [prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca == cb ? 0 : 1)].min }
        prev = cur
      end
      prev.last
    end

    def visible?(pkg, v)
      return true if @locked[pkg] == v
      e = @registry.entry(pkg, v)
      return false if e.yanked
      return false if v.prerelease? && !allow_prerelease_for?(pkg)
      true
    end
  end
end
