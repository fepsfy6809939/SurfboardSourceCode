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

        # === PARAMETERS ===
        boardLength       = getParam('BoardLength')
        railHeight        = getParam('MaxThickness')
        maxWidth          = getParam('MaxWidth')
        segmentLength     = getParam('MinSegmentLength')
        shapeType         = int(getParam('BoardPreset') or 0)
        rockerNose        = getParam('RockerNose')
        rockerTail        = getParam('RockerTail')
        rockerMidOffset   = getParam('RockerMidOffset')
        useStagedRocker   = getParam('UseStagedRocker') or 0
        railStyle         = int(getParam('RailStyle') or 0)
        midBias           = getParam('RailMidBias')
        deckPreset        = int(getParam('DeckRockerPreset') or 0)
        botPreset         = int(getParam('BotRockerPreset') or 0)

        if None in [boardLength, railHeight, segmentLength, midBias]:
            ui.messageBox("❌ Missing one or more required parameters.")
            return

        if segmentLength <= 0:
            ui.messageBox("❌ MinSegmentLength must be greater than 0.")
            return

        # === GET BODY SHAPE ===
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

        # === RAIL FUNCTION ===
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

        # === SETUP SKETCH ===
        sketch = root.sketches.add(root.xZConstructionPlane)
        sketch.name = 'CageSplines'

        numRails = int(math.ceil(boardLength / segmentLength)) + 1
        dz = boardLength / (numRails - 1)
        divisions = 16
        dy = railHeight / divisions

        # === Generate Cage Splines ===
        for d in range(divisions + 1):
            y_local = d * dy
            y_norm = y_local / railHeight
            points = adsk.core.ObjectCollection.create()

            for i in range(numRails):
                z = i * dz
                # Get closest body point to determine true X (width)
                closestPt = min(bodyPoints, key=lambda pt: abs(pt.z - z))
                x_half = abs(closestPt.x)

                x = x_half * railFunc(y_norm)
                normX = x / x_half if x_half != 0 else 0

                if y_local > railHeight / 2:
                    y = y_local + deckRockerOffset(x, normX)
                else:
                    y = y_local + bottomRockerOffset(x, normX)

                y_center = closestPt.y
                y_offset = y_center - (railHeight * midBias)

                points.add(adsk.core.Point3D.create(x, y + y_offset, z))

            sketch.sketchCurves.sketchFittedSplines.add(points)

        ui.messageBox("✅ Longitudinal cage splines generated with full parametric matching.")
        
    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
