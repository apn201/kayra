# lablab submission - texts

Copy field by field. Numbers are from the run of 2026-10-17/18 (artifacts/). Check the character limits in the form; the short description is under 255 characters.

## Project title

Käyrä - identify undocumented controllers from logged data

## Short description

Käyrä works out what an undocumented controller does from data a site already logs. A language model on AMD writes hypotheses as small programs with no numbers; a fitter finds every value and decides. Tested live on a real heating plant.

## Long description

Factories and buildings are full of controllers nobody has documentation for. The integrator left, the vendor is gone. Nobody dares to retune or migrate the loop, because nobody knows what it does. The usual way to find out is a bump test: step the process and watch. That costs production time.

Käyrä does it from data the site already logs. I work as director of IT security and architecture in factories with a lot of legacy OT, so this is a problem I see at work. The proof of concept is my own district heating substation: two heating loops, one commercial controller, Home Assistant room sensors, FMI outdoor temperature. The controller's outputs are not logged, so Käyrä identifies it through the building. Sources, signals and groups are configuration, so the same engine runs on any process.

Each hypothesis about the controller is a short program in a small language: weather curve, curve with summer stop, PI control, thermostat, night setback. The language has no numbers. The model writes the shape and the fitter finds every value, thousands of parameter sets at a time as tensors in PyTorch. So no number in the output comes from the language model.

The language model runs on the AMD token factory (DeepSeek-V4.1-Flash, picked by scoring the endpoint's models on Käyrä's own tasks). It reads what the best program fails to explain and proposes new mechanisms. Every proposal, score and verdict goes into a lab notebook. Operator beliefs are tested the same way. The first entry was mine, "L2 is L1 minus a few degrees", and the panel's own readings refute it.

The model also reads what a plant has lying around. From the labels on the controller's menus (no values) and a few operator notes it wrote the controller's actual setpoint structure as a program: a curve on delayed outdoor temperature with autumn drying and min and max limits. The fitter then says whether the data support it. At the end the model writes the as-found specification, with a summary in Finnish for the technician. Every number in its text is checked against the computed evidence.

From room data alone the curve slope comes out but not the level. A few readings off the panel fix that: the error against readings not used drops from 12.3 °C to 2.2 °C with three. The configured curve, read off the controller by hand, entered the repository after the fits and is graded blind: 15.9 °C off from room data alone, 2.9 °C with three spot readings. I did not know which floor loop L1 heats. Käyrä's own test leans upstairs, the blind evaluation says downstairs. They disagree, so it is not settled, and the report says so.

On synthetic controllers hidden in the real building model, the language-model arm had the lowest held-out error in all 6 cases (4 outright, 2 ties), against 2 for plain grammar search, and used fewer fits. By the mechanism checklist I fixed before the runs, all three arms got 1 of 6. Some of the model's wins come from following seasonal drift. Integrating controllers do not show in room data, and the uncertainty band is too narrow. That is all in the report.

The panel is live: Home Assistant and FMI are read now, and you can move the curve and see where the rooms would settle.

## Technology tags

AMD token factory, DeepSeek-V4.1-Flash, PyTorch, ROCm, Python, Home Assistant, FMI open data, system identification, LLM agents

## Category tags

Intelligent Industry, Industrial AI, OT, building automation, predictive maintenance

## Links

- Live application: [fill: public URL from the helppox deploy]
- Repository: https://github.com/apn201/kayra
- Video: [fill: YouTube URL]
- Slides: docs/slides.pdf in the repository
- Cover image: docs/img/cover.png (1920x1080)
