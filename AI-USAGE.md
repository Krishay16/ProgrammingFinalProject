# AI usage and verification

## Team workflow

The team uses a shared data contract, one branch and pull request per prompt, fixture-based tests and review by teammates. Record the exact tool, material prompts, corrections, tests, reconciliations and manual checks actually performed. Reviewed test output and filing reconciliation should be attributed to the person who performed the work.

## Person 1: Name to complete

* Tools and purpose: TODO by Person 1.
* Prompting, verification and an observed AI error or correction: TODO by Person 1.
* Personal checks and GitHub contribution: TODO by Person 1.

## Person 2: Name to complete

* Tools and purpose: TODO by Person 2.
* Prompting, verification and an observed AI error or correction: TODO by Person 2.
* Personal checks and GitHub contribution: TODO by Person 2.

## Person 3: Name to complete

* Tools and purpose: TODO by Person 3.
* Prompting, verification and an observed AI error or correction: TODO by Person 3.
* Personal checks and GitHub contribution: TODO by Person 3.

## \## Person 4: Krishay

## 

## \### Tools and purpose

## 

## Claude Code was used to assist with the development of the financial ratio engine, credit scoring, risk alerts, stress scenarios and associated unit tests.

## 

## \### Errors caught by automated tests

## 

## \- (4.1) Claude wrote a test expecting the wrong error message for the incomplete SYNTHETIC fixture. Pytest detected the issue. The test was corrected to check the exact error message without changing the application code.

## 

## \### Errors caught by human review before implementation

## 

## \- (4.1) Claude proposed a catch-all exception handler for ratio calculations that could silently hide programming bugs. This approach was rejected to ensure that coding errors cause tests to fail.

## \- (4.2) Claude proposed a leverage scoring rule that could award full leverage points to a company with debt and negative EBITDA. The rule was corrected so that the affected component scores zero, and a dedicated test was added.

## \- (4.3) Claude proposed blanket exception handling around the entire Stress Scenario page. This was restricted to a single try/except around run\_scenario, displaying the actual error.

## \- (4.3) Claude failed to identify that independent revenue and EBIT shocks could mechanically increase operating margins when revenue decreases. In the SYNTHETIC example, the margin increases from 15.0% to 16.7%. This limitation was documented on the page and in methodology.md, and covered by a test.

## 

## \### Errors caught by human review after implementation

## 

## \- (4.3) Claude Code executed the test suite using the system Anaconda Python instead of the project's virtual environment (.venv). The issue was identified through the warning paths. Tests were rerun in the correct environment, with 358 tests passing.

## \- (4.2) Claude changed an approved equity alert threshold from equity < 0 to equity <= 0 without prior approval. The change was disclosed and subsequently accepted by Krishay after reviewing its financial rationale.

## 

## \### Errors caught by AI self-review and verified by Krishay

## 

## \- (4.2) Incorrect capitalisation of EBITDA in ratio labels was corrected using a fixed list of display names.

## \- (4.2) The financial formatter displayed amounts just below one billion as "1000.0m USD". The formatting logic was corrected to round before selecting the unit, and a test was added.

## \- (4.3) Streamlit sliders were assigned values through both fixed defaults and preset buttons, potentially generating warnings. This was corrected before testing.

## \- (4.3) An inconsistent short-term debt warning was corrected to use the application's standard financial field labels.

## 

## \### Process controls

## 

## \- (4.2) Claude attempted to execute a command outside the agreed "only pytest" restriction. The permission prompt prevented the unauthorised execution.

## 

## \### Human oversight and verification

## 

## Krishay reviewed AI-generated implementation plans, challenged financial assumptions, verified generated code, reviewed exceptions and tested edge cases. According to his development report, 358 tests passed in the project's correct virtual environment.Person 5: Samy Hatmi

* **Tool and purpose.** Codex in ChatGPT Work Mode helped interpret the assignment and team contract, implement the dashboard, draft the deterministic commentary and printable report, write tests and prepare supporting documents.
* **Prompting.** Samy supplied the assignment and the team prompts, scoped the task to Person 5, and instructed Codex to preserve shared signatures, use official fixtures, protect private data and report unsuccessful checks.
* **Assistant verification.** Codex ran repository tests and Streamlit checks. For the dashboard it observed 61 passing tests after the local environment was installed. For the commentary it observed 67 passing tests. Fixtures were synthetic. No real-data reconciliation by Person 5 was observed.
* **Correction.** Codex previously interpreted “c’est envoyé” as confirmation that the push had succeeded. Samy's next screenshot showed that Git was still awaiting GitHub sign-in. The assistant corrected the status after the terminal showed the new remote branch. This is a workflow verification error rather than a financial calculation error.
* **Personal verification observed.** Samy installed Git and Python, configured Git identity, checked the staged file list, created and pushed the dashboard commit, and opened PR #2. Further personal code review, number checks and presentation rehearsal are for Samy to document after performing them.
* **Independent review correction.** An AI review found that negative net debt/EBITDA alone cannot establish a net cash position if the denominator is negative. The commentary was changed to look for an explicit negative net debt result.
* **Combined verification.** Codex observed 72 passing tests across the prepared dashboard, commentary and report changes. The report button test verifies the HTML passed to Streamlit. Browser download and verification with the completed analysis engine are pending.

