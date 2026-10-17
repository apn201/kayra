# Video: plan, YouTube texts, tags

Target 3 minutes, 1920x1080, MP4. Screen recording of the live panel plus a few real shots. Voice over or captions, your call. Numbers: read them off the panel when recording, the run on 2026-10-18 may change them.

Nothing with the controller's brand name or logo in the frame: shoot the panel so the printed name is out of shot or blurred. No installer label, no meter serial number.

## Shot list

| # | Time | Shot | What is said |
|---|---|---|---|
| 1 | 0:00-0:15 | Real shot: the controller in the plant room, close on the LCD and buttons (name out of frame). Slow push in. | Factories and buildings are full of controllers nobody has documentation for. This one heats my house. Nobody ever told me what its settings are. |
| 2 | 0:15-0:30 | Panel, Curve screen, as it opens. Status line visible: LIVE, Model AMD. | Käyrä works out what the controller does from data that is already logged. Room temperatures from Home Assistant, outdoor from the weather service. It never touches the controller. |
| 3 | 0:30-1:00 | Curve screen: point at the dots, the curve, the live ring. Switch between upstairs and downstairs. | Each dot is one day of one room. The ring is now. The curve on top is what the controller asks for, found from the rooms alone. |
| 4 | 1:00-1:20 | Drag the slope slider, then the level, watch the room lines and heat input move. Press Fit. | You can move the curve and see where the rooms would settle and what it does to heat input. That comes from the fitted building model. |
| 5 | 1:20-1:55 | AI screen: counters, then the site-context table, the row built from all the menu labels. | A language model on AMD writes the hypotheses as small programs. It can not write a number, the fitter finds every value. I gave it the labels on the controller's menus. It wrote the controller's real setpoint structure from them. The data then says the room data can not support that yet. |
| 6 | 1:55-2:15 | Spot readings screen: k=0, then k=3. The L1 floor note. | Room data alone gets the slope, not the level. Three readings off the panel fix the level. I did not know which floor loop L1 heats. Käyrä's test says upstairs, the blind check against the real settings says downstairs. So it is not settled, and it says so. |
| 7 | 2:15-2:35 | Document screen, scroll to the Finnish summary. | The output is the document the house never had. With a summary in Finnish for the guy who comes to fix it. |
| 8 | 2:35-2:55 | Benchmark screen, then the evaluation result if shown. | On synthetic controllers the language model's programs predicted best in all six cases. It still named the right mechanism only once, same as the plain search. That is in the report too. |
| 9 | 2:55-3:00 | Panel, Curve screen, LIVE. | github.com/apn201/kayra |

B-roll if there is time: the Home Assistant dashboard with the three room sensors; a radiator; the floor-heating manifold.

## YouTube

**Title**

Käyrä - reverse engineering my heating controller from room data (AMD hackathon)

**Description**

I have a heating controller in the basement and no idea what its curve is set to. Nobody does, the installer left the settings and a phone number. Same thing in every factory I have worked with, just more expensive.

Käyrä tries to work out what an undocumented controller is doing from data that is already logged. Here it is the room temperatures from Home Assistant and outdoor temperature from FMI. It never sees the supply water and never touches the controller.

A language model (on AMD's token factory) writes hypotheses about the controller as small programs. It can not put a number in them, the fitter finds every value and decides what survives. I also gave it the labels from the controller's menus, and it wrote the controller's actual setpoint structure from those. The room data was not strong enough to confirm it yet, which is also a result.

Spot readings off the panel fix what room data can not (the curve level). I also did not know which floor the L1 loop heats. Käyrä's own test and the blind check disagree, so that is still open (a hand on the pipes will do).

Built for the AMD Developer Hackathon ACT III, Track 1 Intelligent Industry. Code (MIT): https://github.com/apn201/kayra

Outdoor data: Finnish Meteorological Institute open data, CC BY 4.0.

**Tags**

system identification, heating curve, weather compensation, district heating, Home Assistant, legacy OT, building automation, control systems, PID, AMD, AMD Developer Cloud, ROCm, PyTorch, LLM, language model, DeepSeek, hackathon, lablab, Käyrä, Finland

**Chapters** (if the timings hold)

0:00 The controller nobody documented
0:15 What Käyrä does
0:30 The curve from room data
1:00 Moving the curve
1:20 The language model's job
1:55 Spot readings, and which floor is L1
2:15 The as-found document
2:35 What did not work
