#!/usr/bin/env ruby
# frozen_string_literal: true

require "open3"
require "pathname"
require "tempfile"
require "yaml"

class ContractError < StandardError; end

CHECKOUT_ACTION = "actions/checkout@3d3c42e5aac5ba805825da76410c181273ba90b1"
SETUP_PYTHON_ACTION = "actions/setup-python@5fda3b95a4ea91299a34e894583c3862153e4b97"
SETUP_NODE_ACTION = "actions/setup-node@820762786026740c76f36085b0efc47a31fe5020"

def require_contract(condition, message)
  raise ContractError, message unless condition
end

def load_workflow(directory, name)
  path = directory / name
  require_contract(path.file?, "missing workflow: #{name}")
  data = YAML.safe_load(
    path.read,
    permitted_classes: [],
    permitted_symbols: [],
    aliases: false
  )
  require_contract(data.is_a?(Hash), "#{name} must contain a YAML mapping")
  data
rescue Psych::Exception => e
  raise ContractError, "#{name} is not valid YAML: #{e.message}"
end

def events(workflow, name)
  event_keys = [workflow.key?("on"), workflow.key?(true)].count(true)
  require_contract(event_keys == 1, "#{name} must define exactly one on event mapping")
  value = workflow["on"] || workflow[true]
  require_contract(value.is_a?(Hash), "#{name} must define structured on events")
  value
end

def job(workflow, workflow_name, job_name)
  jobs = workflow["jobs"]
  require_contract(jobs.is_a?(Hash), "#{workflow_name} must define jobs")
  require_contract(
    jobs.keys == [job_name],
    "#{workflow_name} must define only the #{job_name} job"
  )
  value = jobs[job_name]
  require_contract(value.is_a?(Hash), "#{workflow_name} is missing job #{job_name}")
  value
end

def step(job_value, workflow_name, step_name)
  steps = job_value["steps"]
  require_contract(steps.is_a?(Array), "#{workflow_name} job must define steps")
  value = steps.find { |candidate| candidate.is_a?(Hash) && candidate["name"] == step_name }
  require_contract(value.is_a?(Hash), "#{workflow_name} is missing step #{step_name}")
  value
end

def require_exact_steps(job_value, workflow_name, expected_names)
  steps = job_value["steps"]
  require_contract(steps.is_a?(Array), "#{workflow_name} job must define steps")
  names = steps.map { |candidate| candidate.is_a?(Hash) ? candidate["name"] : nil }
  require_contract(
    names == expected_names,
    "#{workflow_name} step names or order changed"
  )
end

def require_exact_mapping_keys(value, expected, message)
  actual = value.keys.map { |key| key == true ? "on" : key.to_s }.sort
  require_contract(actual == expected.sort, message)
end

def executable_lines(run)
  run.lines.each_with_object([]) do |line, lines|
    normalized = line.strip
    next if normalized.empty? || normalized.start_with?("#")

    normalized = normalized.delete_suffix("\\").rstrip
    lines << normalized
  end
end

def require_run_lines(step_value, workflow_name, step_name, required, forbidden = [])
  run = step_value["run"]
  require_contract(run.is_a?(String), "#{workflow_name} step #{step_name} must have a run block")
  lines = executable_lines(run)
  required.each do |required_line|
    require_contract(lines.include?(required_line), "#{workflow_name} step #{step_name} is missing #{required_line}")
  end
  forbidden.each do |fragment|
    require_contract(
      lines.none? { |line| line.include?(fragment) },
      "#{workflow_name} step #{step_name} contains #{fragment}"
    )
  end
end

def require_only_run_line(step_value, workflow_name, step_name, expected)
  run = step_value["run"]
  require_contract(run.is_a?(String), "#{workflow_name} step #{step_name} must have a run block")
  require_contract(
    executable_lines(run) == [expected],
    "#{workflow_name} step #{step_name} must execute only #{expected}"
  )
end

def require_exact_step_keys(step_value, workflow_name, step_name, expected)
  require_contract(
    step_value.keys.map(&:to_s).sort == expected.sort,
    "#{workflow_name} step #{step_name} keys changed"
  )
end

def require_exact_step_env(step_value, workflow_name, step_name, expected)
  require_contract(
    step_value["env"] == expected,
    "#{workflow_name} step #{step_name} environment changed"
  )
end

def require_exact_action_step(step_value, workflow_name, step_name, action, with_values)
  require_exact_step_keys(step_value, workflow_name, step_name, %w[name uses with])
  require_contract(
    step_value["uses"] == action,
    "#{workflow_name} step #{step_name} action changed"
  )
  require_contract(
    step_value["with"] == with_values,
    "#{workflow_name} step #{step_name} inputs changed"
  )
end

def require_exact_run_lines(step_value, workflow_name, step_name, expected)
  run = step_value["run"]
  require_contract(run.is_a?(String), "#{workflow_name} step #{step_name} must have a run block")
  require_contract(
    executable_lines(run) == expected,
    "#{workflow_name} step #{step_name} commands changed"
  )
end

def check_bash_blocks(job_value, workflow_name)
  job_value.fetch("steps", []).each do |step_value|
    next unless step_value.is_a?(Hash) && step_value["run"].is_a?(String)
    next unless step_value.fetch("shell", "bash").to_s.start_with?("bash")

    Tempfile.create(["workflow-run-", ".sh"]) do |file|
      file.write(step_value["run"])
      file.flush
      _stdout, stderr, status = Open3.capture3("bash", "-n", file.path)
      require_contract(
        status.success?,
        "#{workflow_name} step #{step_value['name'] || '<unnamed>'} has invalid shell: #{stderr.strip}"
      )
    end
  end
end

def check_ci_workflow(directory)
  name = "ci.yml"
  workflow = load_workflow(directory, name)
  require_exact_mapping_keys(
    workflow,
    %w[concurrency jobs name on permissions],
    "#{name} top-level keys changed"
  )
  require_contract(workflow["name"] == "Repository checks", "#{name} workflow name changed")
  trigger = events(workflow, name)
  require_contract(
    trigger.keys.sort == %w[pull_request push workflow_dispatch].sort,
    "#{name} must run only for pull_request, main push, and workflow_dispatch"
  )
  require_contract(trigger.dig("push", "branches") == ["main"], "#{name} must validate only main pushes")
  dispatch = trigger["workflow_dispatch"]
  inputs = dispatch.is_a?(Hash) ? dispatch["inputs"] : nil
  base_input = inputs.is_a?(Hash) ? inputs["base_revision"] : nil
  require_contract(
    inputs.is_a?(Hash) && inputs.keys == ["base_revision"] && base_input.is_a?(Hash),
    "#{name} workflow_dispatch must require only base_revision"
  )
  require_contract(
    base_input["required"] == true && base_input["type"] == "string" &&
      base_input["description"].is_a?(String) && !base_input["description"].strip.empty?,
    "#{name} base_revision input must be a required documented string"
  )
  require_contract(workflow["permissions"] == { "contents" => "read" }, "#{name} permissions changed")
  require_contract(
    workflow["concurrency"] == {
      "group" => "surge-ci-${{ github.workflow }}-${{ github.event_name == 'pull_request' && github.ref || github.run_id }}",
      "cancel-in-progress" => "${{ github.event_name == 'pull_request' }}"
    },
    "#{name} concurrency must cancel only superseded runs for the same pull request"
  )

  validate = job(workflow, name, "validate")
  require_exact_mapping_keys(
    validate,
    %w[if runs-on steps timeout-minutes],
    "#{name} validate job keys changed"
  )
  require_contract(validate["runs-on"] == "ubuntu-latest", "#{name} validate runner changed")
  require_contract(validate["timeout-minutes"] == 15, "#{name} validate timeout changed")
  require_exact_steps(
    validate,
    name,
    [
      "Check out repository",
      "Set up Python",
      "Set up Node.js",
      "Check JavaScript syntax",
      "Run JavaScript tests",
      "Check Python syntax and tests",
      "Check shell syntax",
      "Validate release manifest transitions",
      "Validate modules and repository invariants",
      "Check generated rules are reviewed and current"
    ]
  )
  require_contract(
    !validate.key?("permissions"),
    "#{name} validate job must not override top-level read-only permissions"
  )
  require_contract(
    validate["if"] == "github.event_name != 'workflow_dispatch' || github.ref_name == github.event.repository.default_branch",
    "#{name} workflow_dispatch must run only from the default branch"
  )
  checkout = step(validate, name, "Check out repository")
  require_exact_action_step(
    checkout,
    name,
    "Check out repository",
    CHECKOUT_ACTION,
    { "fetch-depth" => 0, "persist-credentials" => false }
  )
  require_exact_action_step(
    step(validate, name, "Set up Python"),
    name,
    "Set up Python",
    SETUP_PYTHON_ACTION,
    { "python-version" => "3.12" }
  )
  require_exact_action_step(
    step(validate, name, "Set up Node.js"),
    name,
    "Set up Node.js",
    SETUP_NODE_ACTION,
    { "node-version" => "22" }
  )
  %w[Check\ JavaScript\ syntax Run\ JavaScript\ tests Check\ Python\ syntax\ and\ tests Check\ shell\ syntax].each do |step_name|
    run_step = step(validate, name, step_name)
    require_exact_step_keys(run_step, name, step_name, %w[name run shell])
    require_contract(run_step["shell"] == "bash", "#{name} step #{step_name} shell changed")
  end
  transition = step(validate, name, "Validate release manifest transitions")
  require_exact_step_keys(transition, name, "Validate release manifest transitions", %w[env if name run shell])
  require_contract(
    transition["shell"] == "bash",
    "#{name} transition step shell changed"
  )
  require_contract(
    transition["if"] == "github.event_name == 'pull_request' || github.event_name == 'push' || github.event_name == 'workflow_dispatch'",
    "#{name} transition step event condition changed"
  )
  env = transition["env"]
  require_contract(
    env == {
      "BASE_REVISION" => "${{ github.event_name == 'pull_request' && github.event.pull_request.base.sha || github.event_name == 'push' && github.event.before || inputs.base_revision }}"
    },
    "#{name} transition step must use the event base revision"
  )
  require_contract(
    executable_lines(transition["run"].to_s) == [
      "set -euo pipefail",
      'python3 scripts/verify-surge-release.py --check-transitions "$BASE_REVISION"'
    ],
    "#{name} transition step commands changed"
  )
  require_exact_step_keys(
    step(validate, name, "Validate modules and repository invariants"),
    name,
    "Validate modules and repository invariants",
    %w[name run]
  )
  generated_step = step(validate, name, "Check generated rules are reviewed and current")
  require_exact_step_keys(
    generated_step,
    name,
    "Check generated rules are reviewed and current",
    %w[name run shell]
  )
  require_contract(
    generated_step["shell"] == "bash",
    "#{name} generated-rules step shell changed"
  )
  check_bash_blocks(validate, name)
end

def check_release_workflow(directory)
  name = "release-integrity.yml"
  workflow = load_workflow(directory, name)
  require_exact_mapping_keys(
    workflow,
    %w[concurrency jobs name on permissions],
    "#{name} top-level keys changed"
  )
  require_contract(workflow["name"] == "Release integrity", "#{name} workflow name changed")
  trigger = events(workflow, name)
  required_events = %w[create push release schedule workflow_dispatch]
  require_contract(
    trigger.keys.sort == required_events.sort,
    "#{name} must run only for create, push, release, schedule, and workflow_dispatch"
  )
  require_contract(trigger.dig("push", "tags")&.include?("*-self-v*"), "#{name} must check self tags")
  schedule = trigger["schedule"]
  require_contract(
    schedule.is_a?(Array) && schedule.any? do |entry|
      entry.is_a?(Hash) && entry["cron"].is_a?(String) && !entry["cron"].strip.empty?
    end,
    "#{name} must define a non-empty scheduled audit cron"
  )
  release_types = trigger.dig("release", "types")
  required_types = %w[created published prereleased released edited unpublished deleted]
  require_contract(
    release_types == required_types,
    "#{name} must use the exact release lifecycle event set"
  )

  verify = job(workflow, name, "verify")
  require_exact_mapping_keys(
    verify,
    %w[if runs-on steps timeout-minutes],
    "#{name} verify job keys changed"
  )
  require_contract(verify["runs-on"] == "ubuntu-latest", "#{name} verify runner changed")
  require_contract(verify["timeout-minutes"] == 10, "#{name} verify timeout changed")
  require_exact_steps(
    verify,
    name,
    [
      "Check out repository",
      "Set up Python",
      "Verify tag payload",
      "Verify published Release",
      "Audit all remote releases"
    ]
  )
  require_contract(
    workflow["concurrency"] == {
      "group" => "surge-release-integrity-${{ github.ref }}",
      "cancel-in-progress" => false
    },
    "#{name} concurrency changed"
  )
  require_contract(
    !verify.key?("permissions"),
    "#{name} verify job must not override top-level read-only permissions"
  )
  require_contract(workflow["permissions"] == { "contents" => "read" }, "#{name} permissions changed")
  require_contract(
    verify["if"] == "github.event_name != 'create' || (github.event.ref_type == 'tag' && contains(github.event.ref, '-self-v'))",
    "#{name} verify job must filter create events to self tags"
  )
  checkout = step(verify, name, "Check out repository")
  require_contract(
    checkout.dig("with", "ref") == "${{ github.event.repository.default_branch }}",
    "#{name} checkout must use the default branch"
  )
  require_exact_action_step(
    checkout,
    name,
    "Check out repository",
    CHECKOUT_ACTION,
    {
      "ref" => "${{ github.event.repository.default_branch }}",
      "fetch-depth" => 0
    }
  )
  require_exact_action_step(
    step(verify, name, "Set up Python"),
    name,
    "Set up Python",
    SETUP_PYTHON_ACTION,
    { "python-version" => "3.12" }
  )

  tag_step = step(verify, name, "Verify tag payload")
  require_exact_step_keys(tag_step, name, "Verify tag payload", %w[env if name run])
  require_exact_step_env(
    tag_step,
    name,
    "Verify tag payload",
    { "RELEASE_TAG" => "${{ github.event_name == 'create' && github.event.ref || github.ref_name }}" }
  )
  require_contract(
    tag_step["if"] == "github.event_name == 'push' || github.event_name == 'create'",
    "#{name} tag verification step condition changed"
  )
  require_only_run_line(
    tag_step,
    name,
    "Verify tag payload",
    'python3 scripts/verify-surge-release.py --tag "$RELEASE_TAG"'
  )
  release_step = step(verify, name, "Verify published Release")
  require_exact_step_keys(release_step, name, "Verify published Release", %w[env if name run])
  require_exact_step_env(
    release_step,
    name,
    "Verify published Release",
    {
      "GITHUB_TOKEN" => "${{ github.token }}",
      "RELEASE_TAG" => "${{ github.event.release.tag_name }}",
    }
  )
  require_contract(
    release_step["if"] == "github.event_name == 'release' && contains(github.event.release.tag_name, '-self-v')",
    "#{name} Release verification step condition changed"
  )
  require_only_run_line(
    release_step,
    name,
    "Verify published Release",
    'python3 scripts/verify-surge-release.py --tag "$RELEASE_TAG" --github-release'
  )
  audit_step = step(verify, name, "Audit all remote releases")
  require_exact_step_keys(audit_step, name, "Audit all remote releases", %w[env if name run])
  require_exact_step_env(
    audit_step,
    name,
    "Audit all remote releases",
    { "GITHUB_TOKEN" => "${{ github.token }}" }
  )
  require_contract(
    audit_step["if"] == "github.event_name == 'schedule' || github.event_name == 'workflow_dispatch'",
    "#{name} remote audit step condition changed"
  )
  require_only_run_line(
    audit_step,
    name,
    "Audit all remote releases",
    "python3 scripts/verify-surge-release.py --check-remote"
  )
  check_bash_blocks(verify, name)
end

def check_rules_workflow(directory)
  name = "rules-drift.yml"
  workflow = load_workflow(directory, name)
  require_exact_mapping_keys(
    workflow,
    %w[concurrency jobs name on permissions],
    "#{name} top-level keys changed"
  )
  require_contract(
    workflow["name"] == "Reviewed managed rules refresh",
    "#{name} workflow name changed"
  )
  trigger = events(workflow, name)
  require_contract(trigger.keys == ["workflow_dispatch"], "#{name} must remain manual-only")
  inputs = trigger.dig("workflow_dispatch", "inputs")
  require_contract(
    inputs.is_a?(Hash) && inputs.keys.sort == %w[rule_set source_commit],
    "#{name} must define only rule_set and source_commit inputs"
  )
  {
    "rule_set" => true,
    "source_commit" => false
  }.each do |input_name, required|
    input = inputs[input_name]
    require_contract(
      input.is_a?(Hash) && input.keys.sort == %w[description required type] &&
        input["required"] == required && input["type"] == "string" &&
        input["description"].is_a?(String) && !input["description"].strip.empty?,
      "#{name} input #{input_name} contract changed"
    )
  end
  require_contract(
    workflow["permissions"] == { "contents" => "write", "pull-requests" => "write" },
    "#{name} permissions changed"
  )
  require_contract(
    workflow["concurrency"] == {
      "group" => "managed-rules-reviewed-refresh",
      "cancel-in-progress" => false
    },
    "#{name} concurrency changed"
  )

  refresh = job(workflow, name, "refresh")
  require_exact_mapping_keys(
    refresh,
    %w[env if runs-on steps timeout-minutes],
    "#{name} refresh job keys changed"
  )
  require_contract(
    refresh["if"] == "github.repository == 'mulanshan/surge'",
    "#{name} repository guard changed"
  )
  require_contract(refresh["runs-on"] == "ubuntu-latest", "#{name} refresh runner changed")
  require_contract(refresh["timeout-minutes"] == 20, "#{name} refresh timeout changed")
  require_exact_steps(
    refresh,
    name,
    [
      "Check out default branch",
      "Set up Python",
      "Create isolated update branch",
      "Refresh explicitly reviewed sources and snapshots",
      "Validate change scope and refreshed snapshots",
      "Commit and push update branch",
      "Open pull request"
    ]
  )
  require_contract(
    !refresh.key?("permissions"),
    "#{name} refresh job must not override workflow permissions"
  )
  env = refresh["env"]
  require_contract(
    env == {
      "BASE_BRANCH" => "${{ github.event.repository.default_branch }}",
      "UPDATE_BRANCH" => "codex/managed-rules-refresh-${{ github.run_id }}-${{ github.run_attempt }}",
      "GH_TOKEN" => "${{ github.token }}",
      "RULE_SET" => "${{ inputs.rule_set }}",
      "SOURCE_COMMIT" => "${{ inputs.source_commit }}"
    },
    "#{name} refresh job environment changed"
  )

  checkout = step(refresh, name, "Check out default branch")
  require_exact_action_step(
    checkout,
    name,
    "Check out default branch",
    CHECKOUT_ACTION,
    {
      "ref" => "${{ github.event.repository.default_branch }}",
      "fetch-depth" => 0
    }
  )
  require_exact_action_step(
    step(refresh, name, "Set up Python"),
    name,
    "Set up Python",
    SETUP_PYTHON_ACTION,
    { "python-version" => "3.12" }
  )
  {
    "Create isolated update branch" => %w[name run shell],
    "Refresh explicitly reviewed sources and snapshots" => %w[name run shell],
    "Validate change scope and refreshed snapshots" => %w[id name run shell],
    "Commit and push update branch" => %w[if name run shell],
    "Open pull request" => %w[if name run shell]
  }.each do |step_name, expected_keys|
    run_step = step(refresh, name, step_name)
    require_exact_step_keys(run_step, name, step_name, expected_keys)
    require_contract(run_step["shell"] == "bash", "#{name} step #{step_name} shell changed")
  end
  require_contract(
    step(refresh, name, "Validate change scope and refreshed snapshots")["id"] == "changes",
    "#{name} change-validation step id changed"
  )
  %w[Commit\ and\ push\ update\ branch Open\ pull\ request].each do |step_name|
    require_contract(
      step(refresh, name, step_name)["if"] == "steps.changes.outputs.changed == 'true'",
      "#{name} step #{step_name} condition changed"
    )
  end
  require_exact_run_lines(
    step(refresh, name, "Create isolated update branch"),
    name,
    "Create isolated update branch",
    [
      "set -euo pipefail",
      'test "$UPDATE_BRANCH" != "$BASE_BRANCH"',
      'git fetch origin "$BASE_BRANCH"',
      'git switch -c "$UPDATE_BRANCH" "origin/$BASE_BRANCH"'
    ]
  )
  require_exact_run_lines(
    step(refresh, name, "Refresh explicitly reviewed sources and snapshots"),
    name,
    "Refresh explicitly reviewed sources and snapshots",
    [
      "set -euo pipefail",
      'args=(--refresh-sources --only "$RULE_SET" --timeout 60)',
      'if [[ -n "$SOURCE_COMMIT" ]]; then',
      'args+=(--source-commit "$SOURCE_COMMIT")',
      "fi",
      'python3 scripts/generate-managed-surge-rules.py "${args[@]}"'
    ]
  )
  require_exact_run_lines(
    step(refresh, name, "Validate change scope and refreshed snapshots"),
    name,
    "Validate change scope and refreshed snapshots",
    [
      "set -euo pipefail",
      'status="$(git status --porcelain=v1 --untracked-files=all)"',
      'if [[ -z "$status" ]]; then',
      'echo "changed=false" >> "$GITHUB_OUTPUT"',
      'echo "Reviewed sources are already current." >> "$GITHUB_STEP_SUMMARY"',
      "exit 0",
      "fi",
      "while IFS= read -r line; do",
      'path="${line:3}"',
      'case "$path" in',
      "rule/Surge/generated/*|rule/Surge/sources/managed-rules.yaml|rule/Surge/upstream/*)",
      ";;",
      "*)",
      'echo "Refresh touched an unexpected path: $path" >&2',
      "exit 1",
      ";;",
      "esac",
      'done <<< "$status"',
      "python3 scripts/generate-managed-surge-rules.py --check --timeout 60",
      'python3 scripts/generate-managed-surge-rules.py --check-upstream --only "$RULE_SET" --timeout 60',
      "python3 .github/scripts/check_repository.py --generated-only",
      'echo "changed=true" >> "$GITHUB_OUTPUT"'
    ]
  )
  require_exact_run_lines(
    step(refresh, name, "Commit and push update branch"),
    name,
    "Commit and push update branch",
    [
      "set -euo pipefail",
      'git config user.name "github-actions[bot]"',
      'git config user.email "41898282+github-actions[bot]@users.noreply.github.com"',
      "git add rule/Surge/sources/managed-rules.yaml rule/Surge/generated rule/Surge/upstream",
      'git commit -m "chore: refresh reviewed managed Surge sources"',
      'git push origin "HEAD:refs/heads/$UPDATE_BRANCH"'
    ]
  )
  push_lines = refresh.fetch("steps", []).flat_map do |step_value|
    next [] unless step_value.is_a?(Hash) && step_value["run"].is_a?(String)

    executable_lines(step_value["run"]).select { |line| line.include?("git push") }
  end
  require_contract(
    push_lines == ['git push origin "HEAD:refs/heads/$UPDATE_BRANCH"'],
    "#{name} must contain exactly one git push to the isolated update branch"
  )
  require_exact_run_lines(
    step(refresh, name, "Open pull request"),
    name,
    "Open pull request",
    [
      "set -euo pipefail",
      'body_file="$(mktemp)"',
      "trap 'rm -f \"$body_file\"' EXIT",
      "{",
      "printf '%s\\n' 'This manually approved maintenance branch refreshed rule set'",
      %q!printf '`%s` after reviewing its moving tracking source.\n\n' "$RULE_SET"!,
      %q!printf 'Source commit (when required): `%s`\n\n' "${SOURCE_COMMIT:-snapshot-only}"!,
      "printf '%s\\n'",
      "'Before merging, review the complete manifest and generated-rule diff,'",
      "'including source SHA-256 changes, rule counts, additions, removals,'",
      "'routing overlap, snapshot bytes, immutable commit provenance, and'",
      %q!printf 'third-party licensing. This workflow never writes directly to `%s`.\n\n' "$BASE_BRANCH"!,
      "printf 'Workflow run: %s/%s/actions/runs/%s\\n'",
      '"$GITHUB_SERVER_URL" "$GITHUB_REPOSITORY" "$GITHUB_RUN_ID"',
      '} > "$body_file"',
      "gh pr create",
      '--base "$BASE_BRANCH"',
      '--head "$UPDATE_BRANCH"',
      '--title "chore: review managed Surge source refresh"',
      '--body-file "$body_file"'
    ]
  )
  check_bash_blocks(refresh, name)
end

begin
  workflow_dir = Pathname.new(ARGV.fetch(0, ".github/workflows")).expand_path
  check_ci_workflow(workflow_dir)
  check_release_workflow(workflow_dir)
  check_rules_workflow(workflow_dir)
  puts "workflow YAML contracts OK"
rescue ContractError, KeyError => e
  warn e.message
  exit 1
end
