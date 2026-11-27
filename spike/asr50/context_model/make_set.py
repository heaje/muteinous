"""Create WP23's independently authored ambiguous-word benchmark."""
from __future__ import annotations

import json
import re
from pathlib import Path

OUT = Path(r"C:\scratch\asr50\WP23")

# Sentence templates below are original benchmark material. The first 30 are
# deliberately clear positives, the next 30 clear negatives, followed by
# contextual contrasts, names, quotations, religion, idioms and homonyms.
clear_yes = [
    ("Damn, that sentry nearly spotted us.", "damn", "profanity"),
    ("What the hell is rattling inside the engine?", "hell", "profanity"),
    ("Screw you, Varo; I am taking the bridge.", "Screw", "profanity"),
    ("That bastard sold our map to the raiders.", "bastard", "profanity"),
    ("You idiot, the beacon is behind you.", "idiot", "profanity"),
    ("This damn lock has jammed again.", "damn", "profanity"),
    ("Hell, we left the medicine on the other ship.", "Hell", "profanity"),
    ("Get your ass off the control panel.", "ass", "profanity"),
    ("Quit bitching and help me lift this crate.", "bitching", "profanity"),
    ("That cowardly jerk abandoned the crew.", "jerk", "profanity"),
    ("God, the alarms are loud tonight.", "God", "deity"),
    ("Jesus, the whole tower is tilting.", "Jesus", "deity"),
    ("Damn it, the relay just burned out.", "Damn", "profanity"),
    ("You stupid fool, the gate is closing.", "fool", "profanity"),
    ("This place is cold as hell.", "hell", "profanity"),
    ("Screw this, we are taking the tunnel.", "Screw", "profanity"),
    ("The captain called me a useless bastard.", "bastard", "profanity"),
    ("You are a lousy thief, and you know it.", "lousy", "profanity"),
    ("Hell, I dropped the key in the dark.", "Hell", "profanity"),
    ("Damn, those drones are fast.", "Damn", "profanity"),
    ("God damn, the lift stopped between floors.", "God", "deity"),
    ("That smug prick stole my seat.", "prick", "profanity"),
    ("Stop acting like a damn fool.", "damn", "profanity"),
    ("Screw the schedule; the convoy leaves now.", "Screw", "profanity"),
    ("What the hell did you do to the reactor?", "hell", "profanity"),
    ("You selfish bastard left us without fuel.", "bastard", "profanity"),
    ("Damn, I thought the passage was clear.", "Damn", "profanity"),
    ("The guard yelled, you miserable idiot.", "idiot", "profanity"),
    ("God, this storm is never going to end.", "God", "deity"),
    ("Hell, that was a close shot.", "Hell", "profanity"),
]
clear_no = [
    ("The priest prayed to God beside the old well.", "God", "deity"),
    ("Jesus taught the village to forgive its enemies.", "Jesus", "deity"),
    ("Lord Arven signed the treaty at sunrise.", "Lord", "deity"),
    ("The scripture describes Hell as a place of punishment.", "Hell", "profanity"),
    ("A screw holds the brass plate to the door.", "screw", "profanity"),
    ("The farmer loaded grain onto his patient ass.", "ass", "profanity"),
    ("Their bitch had five healthy puppies in spring.", "bitch", "profanity"),
    ("The mechanic tightened each screw by hand.", "screw", "profanity"),
    ("Our guide Dick knows every trail in the canyon.", "Dick", "profanity"),
    ("The red cock crowed before the sun appeared.", "cock", "crude"),
    ("The engineer used fire retardant around the wires.", "retardant", "slur"),
    ("The child fell and had bloody knees from the gravel.", "bloody", "profanity"),
    ("The goddess watched over the harbor from her shrine.", "goddess", "deity"),
    ("A small tit perched on the feeder beside the window.", "tit", "crude"),
    ("The guide pointed to the distant Hellfire Ridge.", "Hellfire", "profanity"),
    ("The carpenter found one loose screw in the hinge.", "screw", "profanity"),
    ("The villagers thanked God for the rain.", "God", "deity"),
    ("Saint Peter is named in the old mural.", "Peter", "deity"),
    ("The dog carried a stick in its mouth.", "stick", "profanity"),
    ("A cockatoo landed on the ship's rail.", "cockatoo", "crude"),
    ("The old map labels a valley called Bloody Pass.", "Bloody", "profanity"),
    ("The deity's name was carved into the temple stone.", "deity", "deity"),
    ("A replacement screw came in the repair kit.", "screw", "profanity"),
    ("The baker's ass carried flour sacks to market.", "ass", "profanity"),
    ("The puppy's mother was a gentle bitch.", "bitch", "profanity"),
    ("The Lord of Dawn appears in the legend.", "Lord", "deity"),
    ("A fire-retardant blanket covered the battery.", "retardant", "slur"),
    ("The rooster's cock-a-doodle-doo woke the camp.", "cock", "crude"),
    ("The priest asked God to protect the travelers.", "God", "deity"),
    ("A thin layer of blood covered the cut.", "blood", "profanity"),
]

def case(text: str, word: str, category: str, label: int, group: str) -> dict:
    match = re.search(re.escape(word), text, flags=re.IGNORECASE)
    if match is None:
        raise ValueError(f"Target {word!r} absent from {text!r}")
    start = match.start()
    return {"sentence": text, "target_word": word, "start": start, "end": start + len(word),
            "category": category, "label": label, "group": group}

cases = [case(*x, 1, "clear_positive") for x in clear_yes]
cases += [case(*x, 0, "clear_negative") for x in clear_no]

contrasts = [
 ("The scout screamed bloody murder when the bat flew past.", "bloody", "profanity", 0, "idiom"),
 ("Mara swore bloody murder after the trap snapped shut.", "bloody", "profanity", 1, "profanity"),
 ("The children raised hell by racing through the market.", "hell", "profanity", 1, "idiom"),
 ("The scripture says the wicked descend into hell.", "hell", "profanity", 0, "religious"),
 ("Hell, the northern pass is blocked by snow.", "Hell", "profanity", 1, "interjection"),
 ("Hell House sells warm bread near the station.", "Hell", "profanity", 0, "name"),
 ("God, I forgot to lock the armory.", "God", "deity", 1, "exclamation"),
 ("The villagers left an offering for God at dawn.", "God", "deity", 0, "religious"),
 ("Thank God the children reached the shelter.", "God", "deity", 1, "oath"),
 ("God's mercy gave the survivors hope.", "God", "deity", 0, "religious"),
 ("Jesus, that explosion shook the whole ridge.", "Jesus", "deity", 1, "exclamation"),
 ("Jesus spoke to the crowd beside the river.", "Jesus", "deity", 0, "religious"),
 ("Screw you, the treaty is worthless.", "Screw", "profanity", 1, "insult"),
 ("Please screw the brass panel back into place.", "screw", "profanity", 0, "homonym"),
 ("The crew used a screw to secure the hatch.", "screw", "profanity", 0, "homonym"),
 ("The lieutenant said, \"Damn, the bridge is gone.\"", "Damn", "profanity", 1, "quoted"),
 ("The witness quoted the warning, \"Damn the torpedoes.\"", "Damn", "profanity", 1, "reported"),
 ("The note read, \"God bless this safe harbor.\"", "God", "deity", 0, "quoted"),
 ("The scout reported that the bandit called him an ass.", "ass", "profanity", 1, "reported"),
 ("The farmer said his ass could carry both sacks.", "ass", "profanity", 0, "homonym"),
 ("Bitch, leave the medical kit where it is.", "Bitch", "profanity", 1, "insult"),
 ("The mother bitch guarded her pups from the wolves.", "bitch", "profanity", 0, "animal"),
 ("Lord Veyra ordered everyone to stand down.", "Lord", "deity", 0, "title"),
 ("Lord, the reactor is glowing red again.", "Lord", "deity", 1, "exclamation"),
 ("The saint prayed to the Lord before battle.", "Lord", "deity", 0, "religious"),
 ("Damn, Captain Rook, your plan actually worked.", "Damn", "profanity", 1, "exclamation"),
 ("Damnation is the name of an ancient curse in the play.", "Damnation", "profanity", 0, "mention"),
 ("A damned clever fox stole the ration pack.", "damned", "profanity", 1, "intensifier"),
 ("The condemned were said to be damned forever.", "damned", "profanity", 0, "religious"),
 ("The guard yelled, \"Hell no, we won't surrender!\"", "Hell", "profanity", 1, "quoted"),
 ("The town of Hellgate stands beside the old quarry.", "Hellgate", "profanity", 0, "place"),
 ("Bloody hell, the east gate has vanished.", "Bloody", "profanity", 1, "idiom"),
 ("A bloody nose was the only injury from the fall.", "bloody", "profanity", 0, "literal"),
 ("The crew saw a cock pheasant near the fence.", "cock", "crude", 0, "homonym"),
 ("He made a crude joke about her tits.", "tits", "crude", 1, "crude"),
 ("Blue tits nested under the station roof.", "tits", "crude", 0, "bird"),
 ("The crew called the rude officer a prick.", "prick", "profanity", 1, "insult"),
 ("A prick from the thorn left a mark on his glove.", "prick", "profanity", 0, "literal"),
 ("The medic called the injured man a retard.", "retard", "slur", 1, "slur"),
 ("The label says this chemical is a flame retardant.", "retardant", "slur", 0, "homonym"),
 ("The captain said, \"Screw this; we go by boat.\"", "Screw", "profanity", 1, "quoted"),
 ("They need to screw up the courage to enter.", "screw", "profanity", 0, "idiom"),
 ("The mechanic screwed the lid onto the canister.", "screwed", "profanity", 0, "literal"),
 ("The raider screwed us over and took the supplies.", "screwed", "profanity", 1, "idiom"),
 ("The baron called the sentry a son of a bitch.", "bitch", "profanity", 1, "insult"),
 ("The bitch carried each puppy into the den.", "bitch", "profanity", 0, "animal"),
 ("The oracle spoke of gods sleeping beneath the sea.", "gods", "deity", 0, "religious"),
 ("The warrior shouted, \"Gods, that was close!\"", "Gods", "deity", 1, "exclamation"),
 ("The map marks a ravine named Hell's Mouth.", "Hell", "profanity", 0, "place"),
 ("What the hell did the captain mean by \"later\"?", "hell", "profanity", 1, "profanity"),
 ("Our scout Dick found a hidden path through the reeds.", "Dick", "profanity", 0, "name"),
 ("The guard made a crude remark about his dick.", "dick", "profanity", 1, "crude"),
 ("The officer said, \"Oh God, not another patrol.\"", "God", "deity", 1, "quoted"),
 ("The hymn asks God to guard the valley.", "God", "deity", 0, "religious"),
 ("That damn fool nearly triggered the alarm.", "damn", "profanity", 1, "profanity"),
 ("The Damnwell family runs the ferry at the inlet.", "Damnwell", "profanity", 0, "name"),
 ("The prisoner was damned by the judge's verdict.", "damned", "profanity", 0, "religious"),
 ("The prisoner muttered, \"I'm damned if I do.\"", "damned", "profanity", 1, "idiom"),
 ("The team named its outpost Hell House after a founder.", "Hell", "profanity", 0, "name"),
 ("The team yelled, \"Go to hell, you thief!\"", "hell", "profanity", 1, "insult"),
 ("He asked God for strength before the duel.", "God", "deity", 0, "religious"),
 ("God, that was the loudest thunder I have heard.", "God", "deity", 1, "exclamation"),
 ("The old pilot called the rookie a bastard.", "bastard", "profanity", 1, "insult"),
 ("The bastard sword hung above the blacksmith's bench.", "bastard", "profanity", 0, "homonym"),
 ("A screw fell out of the radio casing.", "screw", "profanity", 0, "homonym"),
 ("Screw the rules, we have to save the crew.", "Screw", "profanity", 1, "profanity"),
 ("The villagers called their shrine the House of the Lord.", "Lord", "deity", 0, "religious"),
 ("Lord, the map is upside down again.", "Lord", "deity", 1, "exclamation"),
 ("The healer said the wound looked bloody but shallow.", "bloody", "profanity", 0, "literal"),
 ("The mercenary shouted, \"Bloody hell, incoming fire!\"", "Bloody", "profanity", 1, "idiom"),
 ("The cock bird strutted beside the coop.", "cock", "crude", 0, "homonym"),
 ("The soldier used a vulgar name for the enemy.", "vulgar", "profanity", 1, "mention"),
 ("The old chapel contains a statue of Jesus.", "Jesus", "deity", 0, "religious"),
 ("Jesus, the bridge is on fire!", "Jesus", "deity", 1, "exclamation"),
 ("The queen said, \"You bastard, return my crown.\"", "bastard", "profanity", 1, "quoted"),
 ("The captain called the child a bastard in anger.", "bastard", "profanity", 1, "insult"),
 ("The village's bitch guarded the sheep from wolves.", "bitch", "profanity", 0, "animal"),
 ("The sentry called the thief a bitch and drew his sword.", "bitch", "profanity", 1, "insult"),
 ("The statue of the Lord stood above the altar.", "Lord", "deity", 0, "religious"),
 ("Oh Lord, I left the radio in the boat.", "Lord", "deity", 1, "exclamation"),
 ("A tiny prick in the balloon made it deflate.", "prick", "profanity", 0, "literal"),
 ("The bully called the mechanic a prick.", "prick", "profanity", 1, "insult"),
 ("The surgeon called the man a retard, then apologized.", "retard", "slur", 1, "slur"),
 ("This spray contains a fire retardant compound.", "retardant", "slur", 0, "homonym"),
 ("The map names the settlement Bloody Ford.", "Bloody", "profanity", 0, "place"),
 ("Bloody fool, you set off the flare.", "Bloody", "profanity", 1, "insult"),
 ("The character's name is Hellan, with two syllables.", "Hellan", "profanity", 0, "name"),
 ("Hell, I was certain the signal was friendly.", "Hell", "profanity", 1, "exclamation"),
 ("The crew prayed to their gods for a safe landing.", "gods", "deity", 0, "religious"),
 ("Gods, the whole cliff face is moving!", "Gods", "deity", 1, "exclamation"),
]
cases.extend(case(*x) for x in contrasts)

if len(cases) != 150:
    raise SystemExit(f"Expected exactly 150 authored cases, got {len(cases)}")
for row in cases:
    assert row["sentence"][row["start"]:row["end"]].casefold() == row["target_word"].casefold()
    assert row["label"] in (0, 1)

(OUT / "labels").mkdir(parents=True, exist_ok=True)
(OUT / "labels" / "wp23_authored.json").write_text(
    json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
print(f"Wrote {len(cases)} original labeled sentences to {OUT / 'labels' / 'wp23_authored.json'}")
