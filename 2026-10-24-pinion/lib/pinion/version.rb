# frozen_string_literal: true

module Pinion
  class ParseError < StandardError; end

  # A SemVer 2.0 version. Build metadata is parsed and kept for display but ignored
  # by ordering and equality, as the spec requires.
  class Version
    include Comparable
    attr_reader :major, :minor, :patch, :pre, :build

    NUM = /0|[1-9]\d*/
    IDENT = /[0-9A-Za-z-]+/
    PATTERN = /\A(#{NUM})\.(#{NUM})\.(#{NUM})(?:-(#{IDENT}(?:\.#{IDENT})*))?(?:\+(#{IDENT}(?:\.#{IDENT})*))?\z/

    def self.parse(str)
      m = PATTERN.match(str.to_s.strip) or raise ParseError, "invalid version #{str.inspect}"
      pre = m[4] ? m[4].split(".") : []
      pre.each { |p| raise ParseError, "invalid version #{str.inspect}: numeric identifier #{p} has a leading zero" if p =~ /\A0\d+\z/ }
      new(m[1].to_i, m[2].to_i, m[3].to_i, pre, m[5] ? m[5].split(".") : [])
    end

    def self.valid?(str)
      parse(str)
      true
    rescue ParseError
      false
    end

    def initialize(major, minor, patch, pre = [], build = [])
      @major = major
      @minor = minor
      @patch = patch
      @pre = pre.freeze
      @build = build.freeze
      freeze
    end

    def prerelease? = !@pre.empty?

    def <=>(other)
      return nil unless other.is_a?(Version)
      c = [major, minor, patch] <=> [other.major, other.minor, other.patch]
      return c unless c.zero?
      return 0 if pre.empty? && other.pre.empty?
      return 1 if pre.empty?        # a release outranks any of its prereleases
      return -1 if other.pre.empty?
      pre.zip(other.pre).each do |a, b|
        return 1 if b.nil?          # longer identifier list wins when prefix is equal
        c = cmp_ident(a, b)
        return c unless c.zero?
      end
      pre.length <=> other.pre.length
    end

    def eql?(other) = other.is_a?(Version) && (self <=> other).zero?
    def hash = [major, minor, patch, pre].hash

    # Smallest version of the next major/minor/patch line; ("-0" is the lowest possible
    # prerelease, so `< 2.0.0-0` excludes 2.0.0's own prereleases like ^ should).
    def next_major = Version.new(major + 1, 0, 0, ["0"])
    def next_minor = Version.new(major, minor + 1, 0, ["0"])
    def next_patch = Version.new(major, minor, patch + 1, ["0"])
    def base = Version.new(major, minor, patch)

    def to_s
      s = +"#{major}.#{minor}.#{patch}"
      s << "-#{pre.join('.')}" unless pre.empty?
      s << "+#{build.join('.')}" unless build.empty?
      s
    end
    alias inspect to_s

    private

    def cmp_ident(a, b)
      an = a.match?(/\A\d+\z/)
      bn = b.match?(/\A\d+\z/)
      return a.to_i <=> b.to_i if an && bn
      return -1 if an   # numeric identifiers sort below alphanumeric ones
      return 1 if bn
      a <=> b
    end
  end
end
