# Opinion or Fact

A science-museum exhibit: visitors place a tagged cube on one of two readers, and the screen shows that cube's "opinion" or "fact" picture.

## Exhibit

**Cube**:
One physical exhibit object, with an RFID tag on each of its six faces, all sharing one image pair and an optional sound.
_Avoid_: Block, item, tag (a tag is only one face of a cube)

**Tag**:
The RFID sticker on one face of a cube, identified by its EPC.
_Avoid_: Card, chip, RFID (as a noun)

**Image pair**:
A cube's two pictures: the D image (opinion) and the U image (fact). Several cubes may share one image pair.
_Avoid_: Slides, content

**Background**:
The picture shown full-screen whenever no cube is showing.
_Avoid_: Idle screen, bg (outside config files)

## Readers

**D reader**:
The reader that shows a cube's D image (*de'a*, Hebrew for opinion).
_Avoid_: Opinion reader, left reader

**U reader**:
The reader that shows a cube's U image (*uvda*, Hebrew for fact).
_Avoid_: Fact reader, right reader

**Role**:
Whether a reader is the D reader or the U reader, remembered per USB socket.
_Avoid_: Side, mode

**Toggle mode**:
The way a lone connected reader works when it has no role: each new placement alternates U image, D image, U image, …
_Avoid_: Alternate mode, single mode

## Behaviour

**Trigger**:
A cube placed on a reader starting its picture (and sound) for the show time.
_Avoid_: Scan, hit, detection

**Re-arm**:
A tag becoming able to trigger again after being away from the reader for a moment; a cube left lying on a reader triggers only once.
_Avoid_: Reset, cooldown

**Registration**:
Telling the exhibit about a new cube: its name, its six tags and its image pair.
_Avoid_: Pairing, enrolling, adding tags

**Sensitivity**:
How close a cube must be to a reader to trigger, set by the minimum signal strength and the reader's transmit power.
_Avoid_: Range (only one of the two knobs), threshold
