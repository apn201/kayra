# Demo video script

Target 3 minutes. Screen recording of the panel (http://localhost:8201 or the Vercel URL), voice over. No Ouman name or logo on screen, no photos of the panel or meter.

Read the numbers off the panel when recording. The ones below are from the 2026-10-17 run and change if it is rerun.

## 0:00 - the problem (20 s)

Show: Curve screen, L1 selected, nothing touched yet.

Say: Factories and buildings have controllers nobody has documentation for. The integrator left, the vendor is gone, nobody dares to retune it. The usual way to find out what a loop does is a bump test, which costs production time. Käyrä does it from data that is already logged.

## 0:20 - the curve (50 s)

Show: Curve screen. Point at the bottom chart dots, then the top curve, then the rings on top.

Say: This is a district heating substation on a real building, two heating loops. Home Assistant sees three rooms, outdoor comes from the Finnish Meteorological Institute. Each dot is one day of one room against outdoor. Käyrä never sees the supply water, only the rooms. It fits a controller and a building model behind them, and this is the curve it found for the downstairs radiators. The rings on top are readings I took off the controller panel by hand. They are not used in the fit.

## 1:10 - move it (30 s)

Show: drag the slope slider, then supply at 0 °C, then press Fit.

Say: You can move the curve. The lines below show where each room would settle and the heat input changes with it. Fit puts it back to the best match. All of this is the fitted building model, nothing is guessed.

## 1:40 - what the model does (40 s)

Show: AI screen. The counters, then the site-context table, the row built from all the menu labels.

Say: Under the curve there is a contest of control structures. A language model reads what the best one fails to explain and writes new ones as small programs. It cannot write a number: the validator rejects any program with a literal in it. A smaller model I tried first got a third of its programs rejected; this one got none. When it needed a zero it wrote "delta minus delta". The fitter finds every value. It also reads what a plant has lying around. From only the labels on the controller's menus it wrote the controller's real setpoint structure: curve on delayed outdoor, autumn drying, min and max limits. The fitter says the room data cannot support that yet. The model reads the plant and the data decides.

Show: Document screen, scroll to the Finnish summary.

Say: At the end it writes the as-found specification, and a summary in Finnish for the technician. Every number in it is checked against the computed evidence.

## 2:10 - spot readings (20 s)

Show: Advanced, Spot readings. Click k=0, k=1, k=3.

Say: From room data alone the slope comes out but the level does not. A few panel readings fix that. Error against the other readings goes from 9.5 °C with none to 1.9 °C with three.

## 2:30 - honesty (25 s)

Show: Benchmark, then the status line.

Say: The synthetic benchmark hides controllers in the real building model. All three arms found one of six. That is the result, and it shows where the method is weak: integrating controllers do not show in room data. AMD Developer Cloud was down on the last day, so the fitter ran on CPU and the model on a stand-in endpoint with the same open model. The status line says so.

## 2:55 - end (5 s)

Show: Curve screen.
