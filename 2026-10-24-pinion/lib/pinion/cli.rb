# frozen_string_literal: true

require "optparse"
require "json"
require_relative "resolver"
require_relative "depgraph"
require_relative "fuzz"

module Pinion
  class UsageError < StandardError; end

  # Exit codes: 0 ok, 1 unsolvable / lock invalid / fuzz failure, 2 bad input or usage.
  class CLI
    HELP = <<~TXT
      pinion — a PubGrub dependency resolver

      usage: pinion <command> [options]

        resolve [MANIFEST]     solve and print the chosen versions
        lock    [MANIFEST]     solve (keeping an existing lock where possible) and write the lockfile
        verify  [MANIFEST]     check a lockfile against manifest + registry without solving
        update  [MANIFEST] [PKG...]   re-lock, changing as little as possible (PKGs: only those; none: everything)
        tree    [MANIFEST]     print the resolved dependency tree
        why     PKG [MANIFEST] explain why PKG is included and what holds it back
        diff    OLD.lock NEW.lock   compare two lockfiles
        graph   [MANIFEST]     write a self-contained HTML dependency graph (-o FILE)
        range   CONSTRAINT [VERSION...]  parse a constraint, show its normal form, test versions
        gen                    emit a random registry + manifest (--seed N)
        fuzz                   differential-test the solver against a brute-force oracle

      common options: --registry FILE (default registry.json)  --lock FILE (default pinion.lock next to MANIFEST)
                      --strategy newest|oldest   --json   --stats
    TXT

    def self.run(argv, out: $stdout, err: $stderr, cwd: Dir.pwd) = new(out, err, cwd).run(argv.dup)

    def initialize(out, err, cwd)
      @out = out
      @err = err
      @cwd = cwd
    end

    def run(argv)
      cmd = argv.shift
      case cmd
      when nil, "help", "-h", "--help" then @out.puts HELP; 0
      when "version", "--version" then @out.puts "pinion 1.0.0"; 0
      when "resolve" then cmd_resolve(argv)
      when "lock" then cmd_lock(argv)
      when "verify" then cmd_verify(argv)
      when "update" then cmd_update(argv)
      when "tree" then cmd_tree(argv)
      when "why" then cmd_why(argv)
      when "diff" then cmd_diff(argv)
      when "graph" then cmd_graph(argv)
      when "range" then cmd_range(argv)
      when "gen" then cmd_gen(argv)
      when "fuzz" then cmd_fuzz(argv)
      else raise UsageError, "unknown command #{cmd.inspect} (try `pinion help`)"
      end
    rescue UsageError, OptionParser::ParseError, ManifestError, RegistryError, LockfileError, ParseError => e
      @err.puts "error: #{e.message}"
      2
    end

    private

    Opts = Struct.new(:registry, :lock, :strategy, :json, :stats, :output, :width, :seed, :packages, :versions,
                      :count, :start, :density, :quiet, :fresh, keyword_init: true)

    def parse(argv, banner)
      o = Opts.new(registry: nil, lock: nil, strategy: :newest, json: false, stats: false, width: 96,
                   seed: 1, packages: 6, versions: 4, count: 200, start: 1, density: 0.35, quiet: false)
      OptionParser.new do |op|
        op.banner = banner
        op.on("--registry FILE") { |v| o.registry = v }
        op.on("--lock FILE") { |v| o.lock = v }
        op.on("--strategy S", %w[newest oldest]) { |v| o.strategy = v.to_sym }
        op.on("--json") { o.json = true }
        op.on("--stats") { o.stats = true }
        op.on("-o", "--output FILE") { |v| o.output = v }
        op.on("--width N", Integer) { |v| o.width = v }
        op.on("--seed N", Integer) { |v| o.seed = v }
        op.on("--packages N", Integer) { |v| o.packages = v }
        op.on("--versions N", Integer) { |v| o.versions = v }
        op.on("--count N", Integer) { |v| o.count = v }
        op.on("--start N", Integer) { |v| o.start = v }
        op.on("--density F", Float) { |v| o.density = v }
        op.on("-q", "--quiet") { o.quiet = true }
        op.on("--fresh", "ignore the lockfile when choosing versions") { o.fresh = true }
      end.parse!(argv)
      o
    end

    # Option state re-expressed as argv, for commands that parse options before the positionals.
    def opts_args(o)
      a = []
      a += ["--registry", o.registry] if o.registry
      a += ["--lock", o.lock] if o.lock
      a += ["--strategy", o.strategy.to_s]
      a << "--json" if o.json
      a << "--fresh" if o.fresh
      a
    end

    def path(p) = File.expand_path(p, @cwd)

    # Parses options, takes an optional manifest path off the front of the positionals.
    def load_project(argv, banner, positional_manifest: true)
      o = parse(argv, banner)
      manifest_arg = positional_manifest ? argv.shift : nil
      manifest_path = path(manifest_arg || "pinion.json")
      manifest = Manifest.load(manifest_path)
      reg_path = path(o.registry || File.join(File.dirname(manifest_path), "registry.json"))
      registry = Registry.load(reg_path)
      lock_path = path(o.lock || File.join(File.dirname(manifest_path), "pinion.lock"))
      [o, manifest, registry, lock_path]
    end

    def lock_prefs(o, lock_path)
      return {} if o.fresh
      lock = read_lock(lock_path)
      lock ? lock.versions : {}
    end

    def read_lock(path, required: false)
      return nil unless File.file?(path) || required
      Lockfile.load(path)
    end

    def solve_or_report(manifest, registry, o, locked: {})
      res = Pinion.resolve(manifest, registry, strategy: o.strategy, locked: locked)
      [res, nil]
    rescue NoSolution => e
      [nil, e]
    end

    def report_failure(manifest, e, o)
      text = Pinion.explain(e, manifest, width: o.width)
      if o.json
        @out.puts JSON.pretty_generate("ok" => false, "explanation" => text.split("\n"))
      else
        @err.puts "error: no set of versions satisfies #{manifest.name}\n\n#{text}"
      end
      1
    end

    def print_solution(manifest, res, o, header: "Resolved")
      if o.json
        @out.puts JSON.pretty_generate("ok" => true, "strategy" => o.strategy.to_s,
                                       "packages" => res.solution.transform_values(&:to_s), "stats" => res.stats)
      else
        @out.puts "#{header} #{res.solution.length} package#{res.solution.length == 1 ? '' : 's'} for #{manifest.name} (#{o.strategy})"
        w = res.solution.keys.map(&:length).max || 0
        res.solution.each { |n, v| @out.puts "  #{n.ljust(w)}  #{v}" }
        @out.puts "  (#{res.stats.map { |k, v| "#{k}: #{v}" }.join(', ')})" if o.stats
      end
    end

    # ---- commands -------------------------------------------------------------

    def cmd_resolve(argv)
      o, manifest, registry, lock_path = load_project(argv, "usage: pinion resolve [MANIFEST]")
      res, err = solve_or_report(manifest, registry, o, locked: lock_prefs(o, lock_path))
      return report_failure(manifest, err, o) if err
      print_solution(manifest, res, o)
      0
    end

    def cmd_lock(argv)
      o, manifest, registry, lock_path = load_project(argv, "usage: pinion lock [MANIFEST]")
      old = read_lock(lock_path)
      res, err = solve_or_report(manifest, registry, o, locked: old ? old.versions : {})
      return report_failure(manifest, err, o) if err
      lock = Lockfile.build(manifest, registry, res.solution)
      lock.write(lock_path)
      if old && !o.json
        d = lock.diff(old)
        @out.puts diff_text(d)
      end
      @out.puts "wrote #{File.basename(lock_path)} (#{res.solution.length} packages)" unless o.json
      @out.puts JSON.pretty_generate("ok" => true, "lock" => lock_path, "packages" => res.solution.length) if o.json
      0
    end

    def cmd_verify(argv)
      o, manifest, registry, lock_path = load_project(argv, "usage: pinion verify [MANIFEST]")
      lock = read_lock(lock_path, required: true)
      problems = lock.verify(manifest, registry)
      if o.json
        @out.puts JSON.pretty_generate("ok" => problems.empty?, "problems" => problems)
      elsif problems.empty?
        @out.puts "lockfile OK (#{lock.packages.length} packages verified against manifest and registry)"
      else
        @err.puts "lockfile is not valid:"
        problems.each { |p| @err.puts "  - #{p}" }
      end
      problems.empty? ? 0 : 1
    end

    def cmd_update(argv)
      o = parse(argv, "usage: pinion update [MANIFEST] [PKG...]")
      # a leading argument naming an existing file is the manifest; everything else is a package
      manifest_arg = argv.first && File.file?(path(argv.first)) ? argv.shift : nil
      targets = argv.dup
      o, manifest, registry, lock_path = load_project(manifest_arg ? [manifest_arg] + opts_args(o) : opts_args(o), "usage: pinion update")
      old = read_lock(lock_path)
      raise UsageError, "no lockfile at #{lock_path}; run `pinion lock` first" unless old
      unknown = targets - old.versions.keys
      raise UsageError, "not in the lockfile: #{unknown.join(', ')}" unless unknown.empty?
      keep = targets.empty? ? {} : old.versions.reject { |n, _| targets.include?(n) }
      res, err = solve_or_report(manifest, registry, o, locked: keep)
      return report_failure(manifest, err, o) if err
      lock = Lockfile.build(manifest, registry, res.solution)
      lock.write(lock_path)
      @out.puts diff_text(lock.diff(old))
      0
    end

    def cmd_tree(argv)
      o, manifest, registry, lock_path = load_project(argv, "usage: pinion tree [MANIFEST]")
      res, err = solve_or_report(manifest, registry, o, locked: lock_prefs(o, lock_path))
      return report_failure(manifest, err, o) if err
      @out.puts DepGraph.new(manifest, res.universe, res.solution).tree
      0
    end

    def cmd_why(argv)
      o = parse(argv, "usage: pinion why PKG [MANIFEST]")
      pkg = argv.shift or raise UsageError, "usage: pinion why PKG [MANIFEST]"
      o, manifest, registry, lock_path = load_project(argv + opts_args(o), "usage: pinion why PKG [MANIFEST]")
      res, err = solve_or_report(manifest, registry, o, locked: lock_prefs(o, lock_path))
      return report_failure(manifest, err, o) if err
      g = DepGraph.new(manifest, res.universe, res.solution)
      @out.puts g.explain_presence(pkg)
      res.solution.key?(pkg) ? 0 : 1
    end

    def cmd_diff(argv)
      parse(argv, "usage: pinion diff OLD.lock NEW.lock")
      raise UsageError, "usage: pinion diff OLD.lock NEW.lock" unless argv.length == 2
      old = Lockfile.load(path(argv[0]))
      new = Lockfile.load(path(argv[1]))
      @out.puts diff_text(new.diff(old))
      0
    end

    def cmd_graph(argv)
      require_relative "htmlreport"
      o, manifest, registry, lock_path = load_project(argv, "usage: pinion graph [MANIFEST]")
      res, err = solve_or_report(manifest, registry, o, locked: lock_prefs(o, lock_path))
      return report_failure(manifest, err, o) if err
      out = path(o.output || "pinion-graph.html")
      File.write(out, HtmlReport.render(manifest, registry, res))
      @out.puts "wrote #{out}"
      0
    end

    def cmd_range(argv)
      parse(argv, "usage: pinion range CONSTRAINT [VERSION...]")
      src = argv.shift or raise UsageError, "usage: pinion range CONSTRAINT [VERSION...]"
      set = Constraint.parse(src)
      @out.puts "#{src.inspect} => #{set}"
      argv.each do |vs|
        v = Version.parse(vs)
        @out.puts "  #{v.to_s.ljust(16)} #{set.include?(v) ? 'matches' : 'does not match'}"
      end
      0
    end

    def cmd_gen(argv)
      o = parse(argv, "usage: pinion gen [--seed N --packages N --versions N]")
      reg, man = Gen.generate(o.seed, packages: o.packages, versions: o.versions, density: o.density)
      if o.output
        dir = path(o.output)
        require "fileutils"
        FileUtils.mkdir_p(dir)
        File.write(File.join(dir, "registry.json"), JSON.pretty_generate(reg) + "\n")
        File.write(File.join(dir, "pinion.json"), JSON.pretty_generate(man) + "\n")
        @out.puts "wrote #{dir}/registry.json and pinion.json"
      else
        @out.puts JSON.pretty_generate("registry" => reg, "manifest" => man)
      end
      0
    end

    def cmd_fuzz(argv)
      o = parse(argv, "usage: pinion fuzz [--count N --start N]")
      sum = Fuzz.run(start: o.start, count: o.count, gen: { packages: o.packages, versions: o.versions, density: o.density }) do |r|
        @err.puts "seed #{r.seed}: #{r.problems.first}" unless r.problems.empty?
      end
      @out.puts "fuzzed #{sum.total} registries (#{sum.sat} satisfiable, #{sum.unsat} unsatisfiable)"
      @out.puts "  learned/proof clauses proven sound by the oracle: #{sum.clauses_checked}"
      @out.puts "  solver work: #{sum.stats.map { |k, v| "#{k}=#{v}" }.join(' ')}"
      if sum.failures.empty?
        @out.puts "  all agree ✓"
        0
      else
        @out.puts "  #{sum.failures.length} DISAGREEMENTS: seeds #{sum.failures.map(&:seed).first(20).join(', ')}"
        1
      end
    end

    def diff_text(d)
      lines = []
      d[:added].sort.each { |n, v| lines << "  + #{n} #{v}" }
      d[:removed].sort.each { |n, v| lines << "  - #{n} #{v}" }
      d[:upgraded].sort.each { |n, (a, b)| lines << "  ↑ #{n} #{a} → #{b}" }
      d[:downgraded].sort.each { |n, (a, b)| lines << "  ↓ #{n} #{a} → #{b}" }
      lines.empty? ? "no changes" : "changes:\n#{lines.join("\n")}"
    end
  end
end
