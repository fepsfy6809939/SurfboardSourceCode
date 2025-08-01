import adsk.core, adsk.fusion, traceback
import math

def run(context):
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct
        root = design.rootComponent

        def getParam(name):
            param = design.userParameters.itemByName(name)
            return param.value if param else None

        # === Parameters ===
        boardLength = getParam('BoardLength')
        railHeight = getParam('MaxThickness')
        segmentLength = getParam('MinSegmentLength')
        railStyle = int(getParam('RailStyle') or 0)
        midBias = getParam('RailMidBias')
        deckPreset = int(getParam('DeckRockerPreset') or 0)
        botPreset = int(getParam('BotRockerPreset') or 0)

        if None in [boardLength, railHeight, segmentLength, midBias]:
            ui.messageBox("❌ Missing one or more required parameters.")
            return

        if segmentLength <= 0:
            ui.messageBox("❌ MinSegmentLength must be greater than 0.")
            return

        # === Sample BoardPlanShape Geometry ===
        planSketch = next((sk for sk in root.sketches if sk.name == 'BoardPlanShape'), None)
        if not planSketch:
            ui.messageBox("❌ Sketch 'BoardPlanShape' not found.")
            return

        bodyPoints = []
        for spline in planSketch.sketchCurves.sketchFittedSplines:
            for pt in spline.fitPoints:
                bodyPoints.append(pt.geometry)

        if len(bodyPoints) < 2:
            ui.messageBox("❌ Not enough points in 'BoardPlanShape'.")
            return

        # === Rail Curve Logic ===
        def railFunc_factory(style):
            def soft(t): return math.sin(t * math.pi / 2)
            def hard(t): return t ** 0.5
            if style == 0: return lambda t: soft(t / midBias) if t < midBias else soft(1 - (t - midBias)/(1 - midBias))
            if style == 1: return lambda t: soft(t / midBias) if t < midBias else hard(1 - (t - midBias)/(1 - midBias))
            if style == 2: return lambda t: hard(t / midBias) if t < midBias else hard(1 - (t - midBias)/(1 - midBias))
            if style == 3: return lambda t: hard(t / midBias) if t < midBias else soft(1 - (t - midBias)/(1 - midBias))
            return lambda t: soft(t)

        railFunc = railFunc_factory(railStyle)

        def deckRockerOffset(x, normX):
            if deckPreset == 0: return 0
            elif deckPreset == 1: return (1 - normX**2) * (railHeight / 2)
            elif deckPreset == 2: return -((1 - normX**2) * (railHeight / 4))
            elif deckPreset == 3: return -railHeight / 4 if normX > (1 - midBias) else 0
            return 0

        def bottomRockerOffset(x, normX):
            if botPreset == 0: return 0
            elif botPreset == 1: return (1 - normX**2) * (railHeight / 4)
            elif botPreset == 2: return abs(normX - 0.5) * (railHeight / 2)
            elif botPreset == 3: return math.sin(normX * math.pi * 2) * (railHeight / 12)
            elif botPreset == 4: return 0 if normX < 0.3 or normX > 0.7 else -railHeight / 5
            elif botPreset == 5: return math.sin(normX * math.pi) * (-railHeight / 3)
            return 0

        # === Generate Rails ===
        numRibs = int(math.ceil(boardLength / segmentLength))
        dz = boardLength / numRibs
        xzPlane = root.xZConstructionPlane

        for i in range(numRibs + 1):
            z_target = i * dz
            closestPt = min(bodyPoints, key=lambda pt: abs(pt.z - z_target))
            z_actual = closestPt.z
            x_half = abs(closestPt.x)
            y_center = closestPt.y

            divisions = 30
            dy = railHeight / divisions
            railPoints = []
            maxY = 0

            for j in range(divisions + 1):
                y_local = j * dy
                y_norm = y_local / railHeight
                x = x_half * railFunc(y_norm)
                normX = x / x_half if x_half != 0 else 0

                y = y_local + deckRockerOffset(x, normX) if y_local > railHeight / 2 else y_local + bottomRockerOffset(x, normX)
                y -= railHeight / 2
                railPoints.append((x, y))
                if y > maxY: maxY = y

            # ✅ FIX: Align top of rail to match board's Y rocker position
            y_offset = y_center - (railHeight * midBias) + (railHeight / 2)

            planeInput = root.constructionPlanes.createInput()
            planeInput.setByOffset(xzPlane, adsk.core.ValueInput.createByReal(z_actual))
            railPlane = root.constructionPlanes.add(planeInput)
            railPlane.name = f'RailPlane_{i:02d}'

            sketch = root.sketches.add(railPlane)
            sketch.name = f'RailSketch_{i:02d}'

            pointCol = adsk.core.ObjectCollection.create()
            for (x, y) in railPoints:
                pointCol.add(adsk.core.Point3D.create(x, y + y_offset, 0))
            sketch.sketchCurves.sketchFittedSplines.add(pointCol)

            # Optional vertical centerline
            if i == 0 or i == numRibs:
                pt1 = adsk.core.Point3D.create(0, y_center, 0)
                pt2 = adsk.core.Point3D.create(0, y_center, 0)
                sketch.sketchCurves.sketchLines.addByTwoPoints(pt1, pt2)

        ui.messageBox("✅ Rail sketches generated with elevation corrected to match board body.")

    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
