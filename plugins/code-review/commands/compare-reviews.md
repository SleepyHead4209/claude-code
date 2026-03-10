---
allowed-tools: Bash(gh pr view:*), Bash(gh pr diff:*), Bash(gh pr list:*), Bash(python3 scripts/compare-analysis.py:*)
description: Run both code-review and pr-review-toolkit agents on the current PR and compare their findings
---

Compare the results from two independent code-analysis passes on the current pull request.

This command runs the two main analysis approaches available in this repository and then compares their findings so you can see which issues were flagged by both (highest confidence) vs. only one tool (investigate further).

## Steps

1. **Verify the PR is reviewable**

   Launch a haiku agent to confirm:
   - The PR is open (not closed or draft)
   - `gh pr view` returns valid PR data

   If the PR is not open, stop and explain why.

2. **Run both analysis passes in parallel**

   Launch the following two sonnet agents **simultaneously** (in parallel):

   **Agent A — confidence-scored agents** (uses `plugins/code-review/commands/code-review.md`):
   Review the pull request following the code-review instructions.  When done, write findings to `tmp_analysis_1.json` using this schema:

   ```json
   {
     "tool": "code-review",
     "issues": [
       {
         "description": "<description of the issue>",
         "file": "<relative file path>",
         "line": <line number or null>,
         "severity": "critical|important|suggestion",
         "confidence": <0-100>
       }
     ]
   }
   ```

   Only include issues with confidence ≥ 80 in the output file.

   **Agent B — specialised review agents** (uses `plugins/pr-review-toolkit/commands/review-pr.md`):
   Review the same pull request following the pr-review-toolkit instructions.  When done, write findings to `tmp_analysis_2.json` using the same schema above but with `"tool": "pr-review-toolkit"`.

   Map pr-review-toolkit severity labels as follows:
   - Critical Issues → `"critical"`
   - Important Issues → `"important"`
   - Suggestions → `"suggestion"`

   Set `confidence` to `90` for Critical, `75` for Important, and `50` for Suggestions.

3. **Compare the two result sets**

   Once both agents have written their JSON files, run:

   ```bash
   python3 scripts/compare-analysis.py tmp_analysis_1.json tmp_analysis_2.json
   ```

   Capture and display the full output.

4. **Present a prioritised action plan**

   Based on the comparison output, produce a summary:

   ```markdown
   ## Analysis Comparison Summary

   ### 🔴 Agreed Issues (found by BOTH tools — fix first)
   - [description] ([file:line])
   - ...

   ### 🟡 Disputed Issues (found by ONE tool — investigate)
   - [tool]: [description] ([file:line])
   - ...

   ### Agreement Score
   X% of all reported issues were corroborated by both analysis passes.

   ### Recommended Actions
   1. Fix all agreed issues immediately — two independent tools flagged them.
   2. Investigate disputed issues; they may be valid but lower-confidence.
   3. Re-run `/compare-reviews` after fixes to verify resolution.
   ```

5. **Clean up temporary files**

   Delete `tmp_analysis_1.json` and `tmp_analysis_2.json` after the comparison is complete.

## Notes

- Both analysis agents run **in parallel** (step 2) for speed.
- Agreed issues have the highest confidence; prioritise them for fixing.
- A high agreement score (> 60%) means the two analysis approaches see the code similarly.
- A low agreement score (< 30%) means each tool found different problems — review all unique findings carefully.
- The comparison uses fuzzy matching on descriptions and file+line numbers, so near-duplicate issues reported at slightly different lines are correctly merged.
