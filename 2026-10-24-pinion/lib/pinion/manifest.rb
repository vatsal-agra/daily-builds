# frozen_string_literal: true

require "json"
require "digest"
require_relative "constraint"

module Pinion
  class ManifestError < StandardError; end

  # A project's requirements:
  #   { "name": "app", "dependencies": { "web": "^2.0" }, "allow_prerelease": ["web"] | true }
  class Manifest
    attr_reader :name, :requirements, :dependencies, :allow_prerelease

    def self.load(path)
      raise ManifestError, "manifest not found: #{path}" unless File.file?(path)
      from_hash(JSON.parse(File.read(path)), source: path)
    rescue JSON::ParserError => e
      raise ManifestError, "#{path}: invalid JSON (#{e.message.lines.first.strip})"
    end

    def self.from_hash(h, source: "manifest")
      raise ManifestError, "#{source}: top level must be an object" unless h.is_a?(Hash)
      new(h, source)
    end

    def initialize(h, source = "manifest")
      @name = h["name"] || "your project"
      raise ManifestError, "#{source}: name must be a string" unless @name.is_a?(String) && !@name.empty?
      deps = h["dependencies"] || {}
      raise ManifestError, "#{source}: dependencies must be an object" unless deps.is_a?(Hash)
      @requirements = {}
      @dependencies = {}
      deps.each do |n, c|
        raise ManifestError, "#{source}: constraint for #{n} must be a string" unless c.is_a?(String)
        @requirements[n] = c
        begin
          @dependencies[n] = Constraint.parse(c)
        rescue ParseError => e
          raise ManifestError, "#{source}: dependency #{n}: #{e.message}"
        end
      end
      ap = h["allow_prerelease"] || []
      unless ap == true || (ap.is_a?(Array) && ap.all?(String))
        raise ManifestError, "#{source}: allow_prerelease must be true or a list of package names"
      end
      # Asking for a prerelease explicitly (">=2.0.0-beta") opts that package in.
      implied = @dependencies.select { |_, s| s.mentions_prerelease? }.keys
      @allow_prerelease = ap == true ? true : (ap + implied).uniq.sort
    end

    # Fingerprint of the requirement set, stored in the lockfile to detect edits.
    def fingerprint
      Digest::SHA256.hexdigest(@requirements.sort.map { |k, v| "#{k} #{v}" }.join("\n") + "\n" + @allow_prerelease.inspect)
    end
  end
end
