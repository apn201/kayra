# Slides outline

Ten slides. Numbers from `artifacts/`, read after the final run. Charts are screenshots of the panel.

1. **Käyrä.** One line: identify an undocumented controller from data the site already logs. Track 1, Intelligent Industry.
2. **The problem.** Controllers nobody has documentation for. Nobody dares to retune or migrate. Bump test costs production time. Author's day job: IT security and architecture in factories full of legacy OT.
3. **Test bench.** District heating substation, two loops, real building, Kouvola. Home Assistant rooms plus FMI outdoor. Controller never touched. Never sees supply temperature. Sample sizes and dates from `real.json` data block.
4. **How.** Diagram: rooms and outdoor in, building model, controller program, fitter, held-out score. The structure language with no numbers. One example program.
5. **The loop.** Model reads the residual, writes programs, validator, fitter, notebook. Screenshot of Notebook screen with a rejected literal and a refuted hypothesis.
6. **What is in the box.** Screenshot of In the box. Ranked per room, ties shown as ties.
7. **Operator belief tested.** OP1: L2 = L1 minus constant. rms constant offset vs scaled, chi-square, verdict.
8. **Spot readings.** Curve screen at k=0 and k=3. Table of error vs k.
9. **Synthetic benchmark.** Arms A / B / C table, right-mechanism counts, fits used. Include the cases nobody got and why (integrator state not observable).
10. **AMD and honesty.** CPU timing measured. GPU row: run on MI300X if it came back, else NOT MEASURED. Model on stand-in endpoint, same open model. Limits list from README.
