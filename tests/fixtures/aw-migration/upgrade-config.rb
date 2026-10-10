#!/usr/bin/env ruby
# frozen_string_literal: true

require "fileutils"
require "optparse"
require "time"
require "tempfile"
require "yaml"

DEFAULT_STEPS = %w[
  prd
  brainstorm
  create_spec
  request_human_review
  plan
  review
  create_tickets
  work
  check_workflow_compliance
  commit
  commit_push_pr
  monitor_pipeline
].freeze

DEFAULT_AUXILIARY = %w[
  refresh
  debug
  create_worktree
  capture
  discover_standards
  research_slack
  pin_behavior
  e2e_tests
  resolve_pr_feedback
  synthesize_memory
].freeze

DEFAULT_E2E = {
  "enabled" => false,
  "trigger_paths" => [],
  "test_paths" => [],
  "run_scope" => "affected"
}.freeze

DEFAULT_CONFIG = {
  "workflow" => {
    "implementation" => {
      "test_policy" => "acceptance-first"
    },
    "steps" => DEFAULT_STEPS.to_h { |step| [step, { "skill" => "" }] },
    "auxiliary" => DEFAULT_AUXILIARY.to_h { |skill| [skill, { "skill" => "" }] },
    "design" => {
      "enabled" => false,
      "reference_paths" => ["docs/standards"],
      "hooks" => {
        "prd_review" => { "skill" => "" },
        "discovery" => { "skill" => "" },
        "spec_review" => { "skill" => "" },
        "plan_review" => { "skill" => "" },
        "ticket_review" => { "skill" => "" },
        "implementation_review" => { "skill" => "" },
        "pre_pr" => { "skill" => "" }
      }
    }
  },
  "pull_request" => {
    "template" => {
      "title" => "",
      "body" => ""
    }
  },
  "git" => {
    "commit" => {
      "format" => "conventional",
      "scope_required" => false,
      "template" => "<type>(<scope>): <description>",
      "allowed_types" => %w[feat fix docs chore refactor test ci build perf style],
      "examples" => [
        "docs(readme): update usage guide"
      ]
    }
  },
  "post_pr" => {
    "ci_monitor" => {
      "provider" => "manual"
    }
  },
  "human_review" => {
    "spec" => {
      "reviewers" => []
    },
    "plan" => {
      "reviewers" => []
    }
  },
  "gates" => {
    "enabled" => false,
    "state_file" => ".aw-gate-state.json",
    "checks" => {
      "review" => { "max_age_hours" => 24 },
      "capture" => { "max_age_hours" => 168 },
      "check_workflow_compliance" => { "max_age_hours" => 24 },
      "synthesize" => { "mode" => "age", "max_age_hours" => 336 }
    }
  },
  "telemetry" => {
    "enabled" => false,
    "path" => "docs/metrics/events.jsonl",
    "rotation" => "monthly",
    "retention_months" => 12
  },
  "tracking" => {
    "enabled" => false,
    "path" => "docs/metrics/skills.jsonl",
    "rotation" => "monthly",
    "retention_months" => 12,
    "session_file" => ".aw/session",
    "session_ttl_hours" => 8
  },
  "org_knowledge" => {
    "source" => "",
    "ref" => "main",
    "cache_dir" => ".aw-org-cache",
    "paths" => {
      "learnings" => "learnings",
      "standards" => "standards"
    }
  },
  "trace" => {
    "enabled" => false,
    "spec_paths" => ["docs/features/*/spec.md"],
    "test_paths" => ["*.feature", "*.test.ts", "*.test.tsx", "*.spec.ts"],
    "code_paths" => ["src"],
    "require_code_anchor" => false
  },
  "pin" => {
    "enabled" => false,
    "manifest_paths" => ["docs/features/*/behavior-pin.yml"],
    "worktree_dir" => ".aw/pin",
    "out" => ".aw/pin/equivalence.json",
    "timeout_seconds" => 900
  },
  "e2e" => DEFAULT_E2E,
  "workflow_trace" => {
    "enabled" => false,
    "path" => ".aw/workflow-trace.jsonl",
    "max_events" => 10000,
    "max_bytes" => 5_242_880,
    "require_tier" => true,
    "required_gates" => ["review", "check_workflow_compliance"]
  }
}.freeze

options = {
  repo: Dir.pwd,
  apply: false
}

OptionParser.new do |parser|
  parser.banner = "Usage: upgrade-config.rb [--repo PATH] [--dry-run] [--apply]"

  parser.on("--repo PATH", "Repository root. Defaults to current directory.") do |path|
    options[:repo] = path
  end

  parser.on("--dry-run", "Preview the migration without writing. This is the default.") do
    options[:apply] = false
  end

  parser.on("--apply", "Write the migrated config and backup the previous file.") do
    options[:apply] = true
  end
end.parse!

def stringify_keys(value)
  case value
  when Hash
    value.each_with_object({}) { |(key, child), memo| memo[key.to_s] = stringify_keys(child) }
  when Array
    value.map { |child| stringify_keys(child) }
  else
    value
  end
end

def deep_merge(base, overlay)
  result = Marshal.load(Marshal.dump(base))
  overlay.each do |key, value|
    result[key] =
      if result[key].is_a?(Hash) && value.is_a?(Hash)
        deep_merge(result[key], value)
      else
        value
      end
  end
  result
end

def dig_hash(hash, *keys)
  keys.reduce(hash) { |memo, key| memo.is_a?(Hash) ? memo[key] : nil }
end

def ensure_hash(hash, key)
  hash[key] = {} unless hash[key].is_a?(Hash)
  hash[key]
end

def blank?(value)
  value.nil? || value == ""
end

def assign_step(config, step, value, source, actions, conflicts)
  return if blank?(value)

  workflow = ensure_hash(config, "workflow")
  steps = ensure_hash(workflow, "steps")
  target = ensure_hash(steps, step)
  existing = target["skill"]

  if !blank?(existing) && existing != value
    conflicts << "#{source} is #{value.inspect}, but workflow.steps.#{step}.skill is already #{existing.inspect}"
    return
  end

  target["skill"] = value
  actions << "migrated #{source} -> workflow.steps.#{step}.skill"
end

def assign_auxiliary(config, key, value, source, actions, conflicts)
  return if blank?(value)

  workflow = ensure_hash(config, "workflow")
  auxiliary = ensure_hash(workflow, "auxiliary")
  target = ensure_hash(auxiliary, key)
  existing = target["skill"]

  if !blank?(existing) && existing != value
    conflicts << "#{source} is #{value.inspect}, but workflow.auxiliary.#{key}.skill is already #{existing.inspect}"
    return
  end

  target["skill"] = value
  actions << "migrated #{source} -> workflow.auxiliary.#{key}.skill"
end

def delete_empty_path(hash, *keys)
  return unless keys.any?

  parents = []
  current = hash
  keys.each do |key|
    return unless current.is_a?(Hash) && current.key?(key)

    parents << [current, key]
    current = current[key]
  end

  parents.reverse_each do |parent, key|
    child = parent[key]
    break unless child.is_a?(Hash) && child.empty?

    parent.delete(key)
  end
end

repo = File.expand_path(options[:repo])
config_path = File.join(repo, "docs", "workflow", "config.yml")
version_path = File.join(repo, ".augmented-workflow-version")
source_root = File.expand_path("../../..", __dir__)
installed_skills_root = File.expand_path("../..", __dir__)
version_file = [
  File.join(source_root, "aw-version.txt"),
  File.join(installed_skills_root, "aw-version.txt")
].find { |path| File.exist?(path) }
unless version_file
  warn "Cannot upgrade config: missing workflow version source aw-version.txt"
  exit 1
end
version = File.read(version_file).strip
if version.empty?
  warn "Cannot upgrade config: empty workflow version source #{version_file}"
  exit 1
end

existing =
  if File.exist?(config_path)
    loaded = YAML.load_file(config_path)
    stringify_keys(loaded || {})
  else
    {}
  end

unless existing.is_a?(Hash)
  warn "Cannot upgrade #{config_path}: expected a YAML mapping at the document root."
  exit 1
end

config = deep_merge(DEFAULT_CONFIG, existing)
actions = []
conflicts = []
notices = []

DEFAULT_AUXILIARY.each do |key|
  misplaced_skill = dig_hash(existing, "workflow", "steps", key, "skill")
  assign_auxiliary(config, key, misplaced_skill, "workflow.steps.#{key}.skill", actions, conflicts)
  config.dig("workflow", "steps")&.delete(key)
end
delete_empty_path(config, "workflow", "steps")

ticket_skill = dig_hash(existing, "ticket_creation", "skill")
assign_step(config, "create_tickets", ticket_skill, "ticket_creation.skill", actions, conflicts)
config.dig("ticket_creation")&.delete("skill")
delete_empty_path(config, "ticket_creation")

commit_skill = dig_hash(existing, "git", "commit", "skill")
assign_step(config, "commit", commit_skill, "git.commit.skill", actions, conflicts)
config.dig("git", "commit")&.delete("skill")
delete_empty_path(config, "git", "commit")
delete_empty_path(config, "git")

research_skill = dig_hash(existing, "research", "slack", "skill")
assign_auxiliary(config, "research_slack", research_skill, "research.slack.skill", actions, conflicts)
config.dig("research", "slack")&.delete("skill")
delete_empty_path(config, "research", "slack")
delete_empty_path(config, "research")

ci_skill = dig_hash(existing, "post_pr", "ci_monitor", "skill")
unless blank?(ci_skill)
  existing_provider = dig_hash(existing, "post_pr", "ci_monitor", "provider")
  if ci_skill.to_s.include?("circleci")
    if !blank?(existing_provider) && existing_provider != "circleci" && existing_provider != "manual"
      conflicts << "post_pr.ci_monitor.skill is #{ci_skill.inspect}, but post_pr.ci_monitor.provider is already #{existing_provider.inspect}"
    else
      ensure_hash(ensure_hash(config, "post_pr"), "ci_monitor")["provider"] = "circleci"
    end
    if ci_skill != "aw-monitor-circleci"
      assign_step(config, "monitor_pipeline", ci_skill, "post_pr.ci_monitor.skill", actions, conflicts)
    else
      actions << "migrated post_pr.ci_monitor.skill=aw-monitor-circleci -> post_pr.ci_monitor.provider=circleci"
    end
  else
    if blank?(existing_provider)
      ensure_hash(ensure_hash(config, "post_pr"), "ci_monitor")["provider"] = "github-actions"
      actions << "set post_pr.ci_monitor.provider=github-actions because post_pr.ci_monitor.skill was configured"
    end
    assign_step(config, "monitor_pipeline", ci_skill, "post_pr.ci_monitor.skill", actions, conflicts)
  end
end
config.dig("post_pr", "ci_monitor")&.delete("skill")
delete_empty_path(config, "post_pr", "ci_monitor")
delete_empty_path(config, "post_pr")

monitor_circleci_skill = dig_hash(existing, "workflow", "steps", "monitor_circleci", "skill")
unless blank?(monitor_circleci_skill)
  existing_provider = dig_hash(existing, "post_pr", "ci_monitor", "provider")
  if !blank?(existing_provider) && existing_provider != "circleci" && existing_provider != "manual"
    conflicts << "workflow.steps.monitor_circleci.skill is #{monitor_circleci_skill.inspect}, but post_pr.ci_monitor.provider is already #{existing_provider.inspect}"
  else
    ensure_hash(ensure_hash(config, "post_pr"), "ci_monitor")["provider"] = "circleci"
  end
  if monitor_circleci_skill == "aw-monitor-circleci"
    actions << "migrated workflow.steps.monitor_circleci.skill=aw-monitor-circleci -> post_pr.ci_monitor.provider=circleci"
  else
    assign_step(config, "monitor_pipeline", monitor_circleci_skill, "workflow.steps.monitor_circleci.skill", actions, conflicts)
  end
end
config.dig("workflow", "steps")&.delete("monitor_circleci")
delete_empty_path(config, "workflow", "steps")

# Consolidate pre-0.5.0 step keys into unified steps
# import_prd + create_prd -> prd
%w[import_prd create_prd].each do |old_step|
  old_skill = dig_hash(existing, "workflow", "steps", old_step, "skill")
  assign_step(config, "prd", old_skill, "workflow.steps.#{old_step}.skill", actions, conflicts)
  config.dig("workflow", "steps")&.delete(old_step)
end
delete_empty_path(config, "workflow", "steps")

# review_code + review_spec + review_plan -> review
%w[review_code review_spec review_plan].each do |old_step|
  old_skill = dig_hash(existing, "workflow", "steps", old_step, "skill")
  assign_step(config, "review", old_skill, "workflow.steps.#{old_step}.skill", actions, conflicts)
  config.dig("workflow", "steps")&.delete(old_step)
end
delete_empty_path(config, "workflow", "steps")

# Consolidate pre-0.5.0 auxiliary keys (check both auxiliary and misplaced-under-steps)
# index_features + refresh_decisions + refresh_solutions -> refresh
%w[index_features refresh_decisions refresh_solutions].each do |old_key|
  aux_skill = dig_hash(existing, "workflow", "auxiliary", old_key, "skill")
  steps_skill = dig_hash(existing, "workflow", "steps", old_key, "skill")
  old_skill = blank?(aux_skill) ? steps_skill : aux_skill
  assign_auxiliary(config, "refresh", old_skill, "workflow.auxiliary.#{old_key}.skill", actions, conflicts)
  config.dig("workflow", "auxiliary")&.delete(old_key)
  config.dig("workflow", "steps")&.delete(old_key)
end

# simplify_code (old auxiliary) -> review (step)
aux_simplify = dig_hash(existing, "workflow", "auxiliary", "simplify_code", "skill")
steps_simplify = dig_hash(existing, "workflow", "steps", "simplify_code", "skill")
simplify_skill = blank?(aux_simplify) ? steps_simplify : aux_simplify
assign_step(config, "review", simplify_skill, "workflow.auxiliary.simplify_code.skill", actions, conflicts)
config.dig("workflow", "auxiliary")&.delete("simplify_code")
config.dig("workflow", "steps")&.delete("simplify_code")

# log_decision + record_retrospective + capture_solution + log_session -> capture
%w[log_decision record_retrospective capture_solution log_session].each do |old_key|
  aux_skill = dig_hash(existing, "workflow", "auxiliary", old_key, "skill")
  steps_skill = dig_hash(existing, "workflow", "steps", old_key, "skill")
  old_skill = blank?(aux_skill) ? steps_skill : aux_skill
  assign_auxiliary(config, "capture", old_skill, "workflow.auxiliary.#{old_key}.skill", actions, conflicts)
  config.dig("workflow", "auxiliary")&.delete(old_key)
  config.dig("workflow", "steps")&.delete(old_key)
end

# clean_artifacts -> removed (cleanup is now aw-refresh cleanup mode; no config key)
aux_clean = dig_hash(existing, "workflow", "auxiliary", "clean_artifacts", "skill")
steps_clean = dig_hash(existing, "workflow", "steps", "clean_artifacts", "skill")
clean_skill = blank?(aux_clean) ? steps_clean : aux_clean
unless blank?(clean_skill)
  actions << "removed workflow.auxiliary.clean_artifacts.skill=#{clean_skill.inspect}; " \
             "cleanup is now aw-refresh cleanup mode (no replacement config key)"
end
config.dig("workflow", "auxiliary")&.delete("clean_artifacts")
config.dig("workflow", "steps")&.delete("clean_artifacts")

delete_empty_path(config, "workflow", "auxiliary")
delete_empty_path(config, "workflow", "steps")

DEFAULT_STEPS.each do |step|
  step_config = ensure_hash(ensure_hash(ensure_hash(config, "workflow"), "steps"), step)
  step_config["skill"] = "" unless step_config.key?("skill")
end

DEFAULT_AUXILIARY.each do |key|
  auxiliary_config = ensure_hash(ensure_hash(ensure_hash(config, "workflow"), "auxiliary"), key)
  auxiliary_config["skill"] = "" unless auxiliary_config.key?("skill")
end

ensure_hash(ensure_hash(config, "workflow"), "implementation")["test_policy"] ||= "acceptance-first"

design = ensure_hash(ensure_hash(config, "workflow"), "design")
design["enabled"] = false unless design.key?("enabled")
design["reference_paths"] = ["docs/standards"] unless design.key?("reference_paths")
design_hooks = ensure_hash(design, "hooks")
%w[prd_review discovery spec_review plan_review ticket_review implementation_review pre_pr].each do |hook|
  hook_config = ensure_hash(design_hooks, hook)
  hook_config["skill"] = "" unless hook_config.key?("skill")
end

e2e = ensure_hash(config, "e2e")
DEFAULT_E2E.each do |key, default|
  e2e[key] = default.dup unless e2e.key?(key)
end

valid_run_scopes = %w[affected full none]
run_scope = dig_hash(config, "e2e", "run_scope")
unless valid_run_scopes.include?(run_scope)
  conflicts << "e2e.run_scope is #{run_scope.inspect}; expected one of #{valid_run_scopes.join(', ')}"
end

valid_policies = %w[
  acceptance-first
  tdd
  bdd
  characterization-first
  test-after
  manual-verification
  none
]
policy = dig_hash(config, "workflow", "implementation", "test_policy")
unless valid_policies.include?(policy)
  conflicts << "workflow.implementation.test_policy is #{policy.inspect}; expected one of #{valid_policies.join(', ')}"
end

# Stage contracts survive entrypoint consolidation. Inspect the resulting stages
# so legacy git.commit.skill is reported too. A name alone is not ownership proof.
{
  "aw-spec" => { "steps" => %w[brainstorm create_spec], "retired" => %w[aw-brainstorm aw-create-spec] },
  "aw-ship" => { "steps" => %w[commit commit_push_pr], "retired" => %w[aw-commit aw-commit-push-pr] }
}.each do |entrypoint, group|
  group["steps"].each do |step|
    provider = dig_hash(config, "workflow", "steps", step, "skill")
    next if blank?(provider)

    if group["retired"].include?(provider)
      notices << "workflow.steps.#{step}.skill=#{provider.inspect} preserved: retired bundled name; " \
                 "verify ownership, then choose #{entrypoint} for the bundled route or keep your custom provider. " \
                 "Exact old slash commands have no universal redirect."
    else
      notices << "workflow.steps.#{step}.skill=#{provider.inspect} preserved independently"
    end
  end
end

changed = config != existing

puts "Augmented Workflow config upgrade"
puts "Repo: #{repo}"
puts "Config: #{config_path}"
puts "Mode: #{options[:apply] ? 'apply' : 'dry-run'}"
puts

if actions.empty?
  puts "Migrations: none"
else
  puts "Migrations:"
  actions.each { |action| puts "- #{action}" }
end

unless notices.empty?
  puts
  puts "Entrypoint migration review (stage keys are unchanged):"
  notices.each { |notice| puts "- #{notice}" }
end

if conflicts.any?
  puts
  puts "Manual review required:"
  conflicts.each { |conflict| puts "- #{conflict}" }
  exit 1
end

unless changed
  puts
  puts "Config already matches the current shape."
  exit 0
end

if options[:apply]
  FileUtils.mkdir_p(File.dirname(config_path))
  if File.exist?(config_path)
    backup = Tempfile.create(["config.yml.bak-#{Time.now.utc.strftime('%Y%m%d%H%M%S')}-", ""], File.dirname(config_path))
    backup_path = backup.path
    backup.close
    FileUtils.cp(config_path, backup_path)
    puts
    puts "Backup: #{backup_path}"
  end

  File.write(config_path, YAML.dump(config))
  File.write(version_path, "#{version}\n")
  puts "Wrote: #{config_path}"
  puts "Wrote: #{version_path}"
else
  puts
  puts "Preview:"
  puts YAML.dump(config)
  puts "Run with --apply to write this config and create a backup."
end
