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

## \## Person 4: Krishay (Ratios, Scoring, Alerts, Engine and Stress Scenario)

## 

## \### Tools used

## 

## \- \*\*Claude Code:\*\* Anthropic, model Claude Opus 5.5, as reported by Krishay, used in VS Code within the local repository on branches `p4/ratios` (4.1), `p4/score-alerts` (4.2) and `p4/scenario-methodology` (4.3). It could read files, edit files and run pytest. It was not allowed to commit or push. Krishay made every commit himself.

## \- \*\*Claude (claude.ai chat):\*\* Used separately as a reviewer for setup, reviewing Claude Code's plans before approval, cross-checking hand calculations, drafting PR descriptions and preparing this documentation. Several issues were identified through this independent review and subsequently corrected through Claude Code.

## 

## \### What the AI was used for

## 

## | Task | AI contribution | Krishay's contribution |

## |---|---|---|

## | 4.1 Ratio functions (src/financial\_calculations.py, 105 tests) | Drafted the 15 ratio functions, helpers (safe\_divide, total\_debt\_value, ebitda\_value) and tests. | Reviewed the plan, accepted additional positive-denominator checks, rejected catch-all error handling, requested round-number tests, cross-checked inputs against sample\_data.py, ran pytest and checked git status. |

## | 4.2 Score, alerts and run\_analysis | Drafted SCORING\_CONFIG, compute\_credit\_score, ALERT\_CONFIG, generate\_alerts, run\_analysis, the money formatter and tests. | Reviewed scoring bands, thresholds, severities, key inputs and expected scores before implementation. Defined negative-equity and boundary rules, corrected leverage treatment for EBITDA <= 0, answered four design questions, requested compact money formatting and compared results from both SYNTHETIC fixtures with hand calculations. |

## | 4.3 Stress scenario (src/scenario.py, src/ui/scenario\_page.py, tests/test\_scenario.py, docs/methodology.md) | Drafted the code, tests and methodology document. | Reviewed and corrected the implementation plan, checked expected results, ran tests in .venv and manually verified the application page. |

## 

## \### How the AI output was controlled

## 

## \- \*\*Plan before code:\*\* For every prompt, the AI read the shared contract and existing code before presenting a plan. Implementation only started after Krishay's approval. From 4.2 onwards, the plan included factor-by-factor arithmetic for the expected SYNTHETIC score: 91.875 in the base case and 78.75 under an EBIT reduction of 20%. Both matched independent hand calculations.

## \- \*\*Hand-calculated tests:\*\* Expected values were documented as arithmetic alongside assertions, for example 500 / 250 = 2.0 and debt/equity increasing from 3,200 / 5,400 to 4,160 / 5,400 under a 30% debt increase.

## \- \*\*No invented documentation values:\*\* Thresholds and examples in docs/methodology.md were derived from the code and actual engine runs on SYNTHETIC fixtures.

## \- \*\*Scope control:\*\* The AI could only modify Person 4's assigned files. During 4.3, the previously implemented ratios, scoring, alerts and engine modules were protected. Git status was checked before every commit.

## \- \*\*Real test results only:\*\* The AI was required to report actual pytest output. Krishay independently reran the tests after each prompt.

## 

## \### AI errors and corrections: Tasks 4.1 and 4.2

## 

## \#### Caught by automated tests

## 

## 1\. \*\*Incorrect expected error message (4.1):\*\* Claude wrote a test expecting the wrong error message for the incomplete SYNTHETIC fixture. Pytest detected the issue. The test was corrected to check the exact message, without modifying the application code.

## 

## \#### Caught by human review before implementation

## 

## 2\. \*\*Catch-all error handling (4.1):\*\* Claude proposed an exception handler that could turn programming bugs into silent undefined ratio results. This was rejected because programming errors must cause tests to fail.

## 

## 3\. \*\*Incorrect leverage scoring (4.2):\*\* The proposed rule would have allowed a company with debt and negative EBITDA to obtain full leverage points from debt/equity alone. The rule was corrected so that the affected half scores zero, with a dedicated test.

## 

## \#### Caught by human review after implementation

## 

## 4\. \*\*Unapproved equity threshold change (4.2):\*\* Claude changed the equity alert threshold from equity < 0 to equity <= 0 without prior approval. It disclosed the change in its report. Krishay accepted the modification after reviewing the rationale, since zero equity would otherwise prevent other leverage alerts from firing.

## 

## \#### Caught by AI self-review and verified by Krishay

## 

## 5\. \*\*Incorrect capitalisation (4.2):\*\* The first draft displayed "Net debt / ebitda". This was corrected using a fixed list of financial ratio labels.

## 

## 6\. \*\*Money formatting and unused code (4.2):\*\* Amounts just below one billion were displayed as "1000.0m USD", and an unused code branch remained. Both issues were corrected. The formatter now rounds before selecting the unit, and a test was added.

## 

## \#### Process controls

## 

## 7\. \*\*Unauthorised command (4.2):\*\* Claude attempted to run a command outside the agreed "only pytest" restriction. The permission prompt blocked the command.

## 

## \#### Requested improvement (not an AI error)

## 

## \- In commit a1cbc02, Krishay requested that score explanations display compact financial amounts with currency, such as "-500.0m USD" instead of "-500,000,000". The underlying stored values remained unchanged.

## 

## \### AI errors and corrections: Task 4.3

## 

## 1\. \*\*Specification creep:\*\* Claude proposed adding a redundant fiscal\_year field to ScenarioResult. This was rejected because the page can access stressed\_period.fiscal\_year.

## 

## 2\. \*\*Overly broad error handling:\*\* Claude proposed wrapping the entire Stress Scenario page in exception handling. Krishay required explicit handling of known cases, including missing data, missing periods and insufficient scores, with at most one try/except displaying the actual error.

## 

## 3\. \*\*Missing financial limitation:\*\* Claude did not identify that reducing revenue while keeping EBIT unchanged mechanically increases the operating margin. In the SYNTHETIC example, 1,350 / 8,100 = 16.7%, compared with the original 15.0%. This limitation was documented in the methodology, displayed on the page and covered by a test.

## 

## 4\. \*\*Streamlit slider bug:\*\* The initial implementation assigned slider values in two different ways, generating a potential Streamlit warning. Claude identified and corrected the issue before testing.

## 

## 5\. \*\*Inconsistent message wording:\*\* Missing-value messages used code field names such as "Short term debt". Claude flagged the wording, and Krishay requested the use of the shared FIELD\_LABELS.

## 

## 6\. \*\*Incorrect Python environment:\*\* Claude executed the test suite using system Anaconda Python instead of the project's .venv. Krishay identified the issue through the anaconda3 paths in the warning output. Tests were rerun in the correct environment using pytest 9.2.0, with 358 tests passing.

## 

## 7\. \*\*Commands beyond the agreed scope:\*\* Claude executed additional read-only commands, including file reads and a script displaying engine results. Each command was individually approved by Krishay through the permission prompt.

## 

## \### Personal verification by Krishay

## 

## \#### Automated testing

## 

## | Development stage | Tests passed |

## |---|---:|

## | 4.1 Ratio functions | 158 |

## | 4.2 Scoring and alerts | 334 |

## | 4.3 Stress scenario | 358 |

## 

## The final test run was performed in the project virtual environment using `python -m pytest` and pytest 9.2.0: 358 passed, 0 failed.

## 

## Before every commit, Krishay checked git status to confirm that only his assigned files had been modified.

## 

## \#### Financial ratio verification (4.1)

## 

## The FY2024 input values used in the tests were cross-checked against tests/fixtures/sample\_data.py. All values matched.

## 

## \#### Credit scoring verification (4.2)

## 

## Krishay ran run\_analysis on both SYNTHETIC fixtures:

## 

## \- \*\*Healthy company:\*\* Score of 91.875, classified as "Lower Indicative Financial Risk". The factor breakdown was 15 / 21.875 / 20 / 20 / 15, matching the independent hand calculation.

## \- \*\*Incomplete company:\*\* Insufficient data, with partial factors of 5 / 0 / 10 / None / None. Alerts were generated for liquidity (medium severity), negative equity (high severity) and data quality (high severity).

## 

## \#### Application verification (4.2)

## 

## Krishay ran `streamlit run app.py` and verified that every page opened without crashing.

## 

## \#### Stress Scenario verification (4.3)

## 

## The SYNTHETIC demo company was loaded and the following results were manually verified:

## 

## | Scenario | Credit score |

## |---|---:|

## | Base case | 91.875 |

## | No shock | 91.875 |

## | EBIT -20% | 78.75 |

## | Revenue -10% and EBIT -25% | 78.75 |

## | Debt +30% | 88.75 |

## | Reset | 91.875 |

## 

## Additional checks:

## 

## \- The SCENARIO\_LABEL banner was displayed.

## \- Scenario assumptions and the disclaimer were visible.

## \- Without a loaded company, the page displayed "No confirmed financial data" and a "Go to Search" button.

## 

## \#### Verification limitations

## 

## Person 4 did not test the engine using real SEC or PDF financial data. Verification was limited to SYNTHETIC fixtures.

## 

## \### Limits and responsibility

## 

## The AI generated most of the code text. Krishay specified the design, reviewed every implementation plan, checked the financial logic, independently verified expected results and made the final implementation decisions. He remains responsible for the resulting work.

## 

## The information in this section was supplied by Krishay and consolidated into AI-USAGE.md by Samy.

## 

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

