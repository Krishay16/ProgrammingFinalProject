# AI usage and verification

## Team workflow
The team uses a shared data contract, one branch and pull request per prompt, fixture-based tests and review by teammates. Record the exact tool, material prompts, corrections, tests, reconciliations and manual checks actually performed. Reviewed test output and filing reconciliation should be attributed to the person who performed the work.

## Person 1: Name to complete
- Tools and purpose: TODO by Person 1.
- Prompting, verification and an observed AI error or correction: TODO by Person 1.
- Personal checks and GitHub contribution: TODO by Person 1.

## Person 2: Name to complete
- Tools and purpose: TODO by Person 2.
- Prompting, verification and an observed AI error or correction: TODO by Person 2.
- Personal checks and GitHub contribution: TODO by Person 2.

## Person 3: Name to complete
- Tools and purpose: TODO by Person 3.
- Prompting, verification and an observed AI error or correction: TODO by Person 3.
- Personal checks and GitHub contribution: TODO by Person 3.

## Person 4: Name to complete
- Tools and purpose: TODO by Person 4.
- Prompting, verification and an observed AI error or correction: TODO by Person 4.
- Personal checks and GitHub contribution: TODO by Person 4.

## Person 5: Samy Hatmi
- **Tool and purpose.** Codex in ChatGPT Work Mode helped interpret the assignment and team contract, implement the dashboard, draft the deterministic commentary and printable report, write tests and prepare supporting documents.
- **Prompting.** Samy supplied the assignment and the team prompts, scoped the task to Person 5, and instructed Codex to preserve shared signatures, use official fixtures, protect private data and report unsuccessful checks.
- **Assistant verification.** Codex ran repository tests and Streamlit checks. For the dashboard it observed 61 passing tests after the local environment was installed. For the commentary it observed 67 passing tests. Fixtures were synthetic. No real-data reconciliation by Person 5 was observed.
- **Correction.** Codex previously interpreted “c’est envoyé” as confirmation that the push had succeeded. Samy's next screenshot showed that Git was still awaiting GitHub sign-in. The assistant corrected the status after the terminal showed the new remote branch. This is a workflow verification error rather than a financial calculation error.
- **Personal verification observed.** Samy installed Git and Python, configured Git identity, checked the staged file list, created and pushed the dashboard commit, and opened PR #2. Further personal code review, number checks and presentation rehearsal are for Samy to document after performing them.
- **Independent review correction.** An AI review found that negative net debt/EBITDA alone cannot establish a net cash position if the denominator is negative. The commentary was changed to look for an explicit negative net debt result.
- **Combined verification.** Codex observed 72 passing tests across the prepared dashboard, commentary and report changes. The report button test verifies the HTML passed to Streamlit. Browser download and verification with the completed analysis engine are pending.
