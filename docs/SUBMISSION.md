# Submission text - drafts for Juha to edit

lablab character limits not checked: [fill: short and long description limits from the submit form]

## Title

Käyrä - identify undocumented controllers from logged data

## Short description

Käyrä works out what an undocumented controller does from the data a site already logs. No manual, no bump test. A language model writes hypotheses as small programs, a GPU fitter scores them against months of history. Tested on a real district heating substation.

## Long description

Factories and buildings are full of controllers nobody has documentation for. The integrator left a decade ago, the vendor is gone. Nobody dares to retune the loop or migrate it, because nobody knows what it does. The usual way to find out is a bump test: step the process and watch. That costs production time.

Käyrä does it from data the site already logs. I work as director of IT security and architecture in factory environments with a lot of legacy OT, so this is a problem I see at work. The test bench is a district heating substation on a real building in Kouvola, with Home Assistant room sensors and FMI outdoor temperature. Käyrä never sees the controller's output, only rooms and outdoor. So it has to identify the controller through the building.

Each hypothesis about the controller is a short program in a small language: weather curve, curve with summer cutoff, PI on room temperature, thermostat, night setback. The language has no numbers. The model writes the shape and the fitter finds every value, thousands of parameter sets at a time as tensors. So no number in the output comes from the language model. The validator rejects any program with a literal in it, and the model gets one chance to repair it.

The language model reads what the best program fails to explain and proposes new mechanisms. Every proposal, score and verdict goes into a lab notebook. Operator beliefs are tested the same way. The first entry was mine: "L2 is L1 minus a few degrees". The panel's own readings refute it, the gap widens when it gets colder.

The model also reads what a plant actually has lying around. Given only the labels on the controller's menu screens (no values) and a few operator notes, it wrote the controller's documented setpoint structure as a program: a curve on delayed outdoor temperature, plus an autumn drying term, clamped by min and max limits. The fitter then said the room data cannot support that much structure yet. The model reads the plant and the data decides. At the end the model writes the as-found specification for the engineer, with a short summary in Finnish for the technician, and every number in it is checked against the computed evidence.

From room data alone the curve slope is identifiable but the level is not. A technician can always read the panel a few times, so Käyrä takes spot readings. With no readings the curve misses the other panel readings by 9.5 °C. With three it is 1.9 °C.

A synthetic benchmark puts hidden controllers into the real building model and compares three arms: seed catalogue only, catalogue plus random grammar search, catalogue plus the language model. Result: all three arms recovered 1 of 6 by the checklist I fixed before the runs, and that one is generous (the found program filters only the cutoff, not the curve), so strictly 0 of 6. The language model did not beat the baseline here. The oracle checks show why: integrator state does not show in room data, and several mechanisms barely change the room temperature. I report it as it is.

AMD Developer Cloud was down on the last build day. The fitter is PyTorch and runs on ROCm unchanged, but the numbers in this version are from CPU, and the model ran on an OpenRouter stand-in with DeepSeek-V4.1-Flash, a model that is also on the AMD token factory. The panel says so in its status line. [fill: update if AMD comes back before deadline]

## Tags

Technology: AMD Developer Cloud, ROCm, PyTorch, vLLM, Qwen3 Coder, Home Assistant, Vercel
Category: Intelligent Industry, system identification, legacy OT, building automation

## Checklist

- [ ] Cover image 16:9 PNG/JPG
- [ ] Demo video MP4 (docs/DEMO_SCRIPT.md)
- [ ] Slides PDF (docs/SLIDES.md)
- [ ] Public GitHub repo, MIT, `python tools/check_secrets.py` clean
- [ ] Live URL (Vercel)
- [ ] No Ouman name or logo in UI or video, no panel or meter photos
