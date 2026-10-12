#!/usr/bin/env bash
# The official SWE-Marathon tests for this task, fetched rather than vendored: they are somebody
# else's work under their own licence, and a copy here would go stale against upstream.
#
# Sparse-checkouts tasks/slack-clone from github.com/abundant-ai/swe-marathon into ./official/.
set -euo pipefail
cd "$(dirname "$0")"
rm -rf .swe-marathon official
git clone --no-checkout --depth 1 --filter=blob:none \
  https://github.com/abundant-ai/swe-marathon.git .swe-marathon
cd .swe-marathon
git sparse-checkout init --cone
git sparse-checkout set tasks/slack-clone
git checkout
cd ..
mv .swe-marathon/tasks/slack-clone official
rm -rf .swe-marathon
cat <<'EOF'

official/ now holds the task's own tests.

The five correctness gates, none of which involve the Computer-Use grader:

  api        test_api, test_profiles, test_read_state, test_channels_extra, test_files,
             test_slash, test_groups, test_invitations, test_roles, test_cluster,
             test_ordering, test_load          (12 files, 129 test functions)
  irc        test_irc                          (11)
  crash      test_crash                        (3)   needs /proc: Linux only
  chaos      test_chaos                        (3)   needs /proc: Linux only
  frontend   test_frontend                     (3)

Excluded on purpose:
  cua_verifier.py, cua_blend.sh, cua_stage.sh, cua_config.json, rubric.json
      the Computer-Use rubric, which grades UX in a browser rather than the code
  test_e2e.py, journey_onboarding.py
      Playwright plus a chromium build

Run them against an implementation with:
  python3 ../../eval/grader/run_gates.py <impl dir> --tests ./official/tests \
      --python <a venv python with pytest requests websockets> --out /tmp/grade
EOF
