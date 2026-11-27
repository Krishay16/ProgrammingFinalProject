# SolvIQ | Eight-minute presentation

## Run of show and speaker notes

| Time | Speaker | Screen | What to say and do |
| --- | --- | --- | --- |
| 0:00–0:55 | Person 1 | Slide 1 | “A first-pass screen is only as useful as the evidence a reviewer can trace. SolvIQ brings figures, ratios, alerts and source references into one screening workflow. We will show how an analyst moves from a confirmed company to a reviewable report.” |
| 0:55–2:10 | Person 2 | Slide 2, live search | “I start with Microsoft and confirm the ticker and issuer. These periods come from SEC EDGAR. Notice the fiscal year-end and currency. Before presenting any figure as reconciled, we check the exact period, filing and units against the evidence.” Open the proven public case only after rehearsal. |
| 2:10–3:10 | Person 3 | Slide 3, input fallback | “When the supported source does not cover a company, the analyst can upload statements or enter figures. Here is how I confirm a value and leave a missing cell blank. An API outage is a different case and should produce a different message.” Use permitted synthetic files. |
| 3:10–4:35 | Person 5 | Slide 4, dashboard | “The dashboard takes the engine outputs. Open a ratio to see the formula and inputs. A gap means the value is unavailable. The commentary separates an observation from its interpretation and runs locally. The HTML report carries the sources and limitations into the review.” Download and open the HTML report. |
| 4:35–5:55 | Person 4 | Slide 5 | “The four input paths use the same confirmed model. The analysis engine owns the calculations. One way to validate the workflow is to reconcile a source figure, independently calculate the ratio and then confirm that the dashboard displays the same result. Missing inputs can leave the score incomplete. The policy is illustrative.” Show a real tested example only once verified. |
| 5:55–8:00 | Person 5, then Person 1 | Slides 6–7 | Samy: “The analyst moves from repeated transcription to verifying exceptions. The reviewer can reproduce selected checks from the report. That is our modest SDG 9 contribution. The local commentary needs no external provider.” Person 1: “Our ask is approval for a controlled pilot. Compare matched cases and measure reviewer rework, traceability and time to a reviewable screening file.” |

## Live demonstration checklist

1. Open a prepared application tab. Confirm the SEC path and filings can be reached.
2. Select the verified Microsoft result and record the fiscal year, currency and source.
3. Rehearse a no-coverage case and an unavailable-service case separately. Confirm manual or PDF fallback and a corrected value.
4. Open an available ratio, an unavailable ratio if present, score factors and source details. Open commentary and download HTML. Check the exported value matches the screen.
5. Where a step remains unavailable on presentation day, state the limitation and show the closest verified alternative. Distinguish public and synthetic evidence on screen.
6. Rehearse at eight minutes with all five speakers and reserve four minutes for questions.

## Recorded fallback

Record a clean run after integration. Capture the selected screen and narrate the source, period, metric and missing-data behavior. Include the dashboard, the fallback route and the downloaded HTML. Prepare a local video and a local copy of the HTML. Test playback on a second machine and confirm captions and audio. If live SEC access fails, state that explicitly and play the recorded public case or use the labelled synthetic case if it is the only proven fallback. Recording remains a team rehearsal action.

## Four-minute Q&A

| Owner | Likely question | Suggested answer |
| --- | --- | --- |
| Person 1 | How do pages share data and handle a company change? | “The confirmed statements are stored through shared state helpers. Changing the confirmed company invalidates the stored analysis so the dashboard can request fresh results.” |
| Person 1 | What did you test independently? | “I would show the actual acceptance record and distinguish local tests from live data checks. I would report any test that could not be run.” |
| Person 2 | How do you validate a real filing number? | “Match the issuer, report date, filing reference, XBRL tag and currency units. Compare the extracted amount to the source before validating any derived metric.” |
| Person 2 | What happens when EDGAR fails? | “An outage indicates a retrieval problem. The UI distinguishes it from lack of supported statements and offers fallback routes.” |
| Person 3 | How do you deal with conflicting PDF values? | “Ambiguous values require analyst confirmation. Scanned or unusable statements can be routed to manual entry.” |
| Person 3 | Does a blank cell become a zero? | “It stays missing. A typed zero has a different financial meaning and is preserved.” |
| Person 4 | What if current liabilities are zero? | “A zero denominator makes the current ratio undefined, so the engine supplies that status and reason. A missing input produces an unavailable result.” |
| Person 4 | Is the score a default probability? | “It is an illustrative first-pass screen for non-financial corporates. Incomplete evidence can prevent a full score.” |
| Person 5 | Where does a value on the chart come from? | “The dashboard reads confirmed values and engine outputs. It rescales currency into millions and decimal margins into percentages for display.” |
| Person 5 | How do you control unsupported AI claims? | “This release generates commentary locally using fixed rules and actual validated results. An unavailable ratio produces a reason and is carried into the missing-information list.” |
| Person 5 | How do you prevent injection in the report? | “All dynamic text is HTML-escaped. The report uses inline CSS and needs no external assets. Tests cover hostile company names and source labels.” |
| Person 5 | What impact on SDG 9 can you defend? | “A smaller team can evaluate a traceable workflow using free public data where available. We would measure traceability and review effort in a pilot. Lending outcomes require separate evidence.” |
