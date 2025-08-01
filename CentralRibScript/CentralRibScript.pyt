import adsk.core, adsk.fusion, traceback
import math

def run(context):
    try:
        # === Setup ===
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct
        root = design.rootComponent

        def getParam(name):
            param = design.userParameters.itemByName(name)
            return param.value if param else None

        # === Parameters ===
        boardLength     = getParam('BoardLength')
        railHeight      = getParam('MaxThickness')  # Only once now
        maxWidth        = getParam('MaxWidth')
        segmentLength   = getParam('MinSegmentLength')
        railStyle       = int(getParam('RailStyle') or 0)
        midBias         = getParam('RailMidBias')
        deckPreset      = int(getParam('DeckRockerPreset') or 0)
        botPreset       = int(getParam('BotRockerPreset') or 0)
        shellThickness  = getParam('ShellThickness')
        ribThickness    = getParam('CenterRibThickness')

        if None in [boardLength, railHeight, segmentLength, midBias, shellThickness, ribThickness]:
            ui.messageBox("❌ Missing one or more required parameters.")
            return

        # === Get Board Shape ===
        planSketch = next((sk for sk in root.sketches if sk.name == 'BoardPlanShape'), None)
        if not planSketch:
            ui.messageBox("❌ Sketch 'BoardPlanShape' not found.")
            return

        bodyPoints = [pt.geometry for spline in planSketch.sketchCurves.sketchFittedSplines for pt in spline.fitPoints]
        if len(bodyPoints) < 2:
            ui.messageBox("❌ Not enough points in 'BoardPlanShape'.")
            return

        # === Construct Midplane ===
        xzPlane = root.xZConstructionPlane
        zMid = boardLength / 2
        planeInput = root.constructionPlanes.createInput()
        planeInput.setByOffset(xzPlane, adsk.core.ValueInput.createByReal(zMid))
        railPlane = root.constructionPlanes.add(planeInput)
        railPlane.name = 'TrimmedRailPlane'

        # === Get closest X/Y half-width at midpoint ===
        closestPt = min(bodyPoints, key=lambda pt: abs(pt.z - zMid))
        xHalf = abs(closestPt.x)
        yCenter = closestPt.y

        # === Rail Shape Function ===
        def railFunc_factory(style):
            def soft(t): return math.sin(t * math.pi / 2)
            def hard(t): return t ** 0.5
            if style == 0:
                return lambda t: soft(t / midBias) if t < midBias else soft(1 - (t - midBias) / (1 - midBias))
            if style == 1:
                return lambda t: soft(t / midBias) if t < midBias else hard(1 - (t - midBias) / (1 - midBias))
            if style == 2:
                return lambda t: hard(t / midBias) if t < midBias else hard(1 - (t - midBias) / (1 - midBias))
            if style == 3:
                return lambda t: hard(t / midBias) if t < midBias else soft(1 - (t - midBias) / (1 - midBias))
            return lambda t: soft(t)

        railFunc = railFunc_factory(railStyle)

        # === Rocker Offset Functions ===
        def deckRockerOffset(x, normX):
            if deckPreset == 0: return 0
            if deckPreset == 1: return (1 - normX**2) * (railHeight / 2)
            if deckPreset == 2: return -((1 - normX**2) * (railHeight / 4))
            if deckPreset == 3: return -railHeight / 4 if normX > (1 - midBias) else 0
            return 0

        def bottomRockerOffset(x, normX):
            if botPreset == 0: return 0
            if botPreset == 1: return (1 - normX**2) * (railHeight / 4)
            if botPreset == 2: return abs(normX - 0.5) * (railHeight / 2)
            if botPreset == 3: return math.sin(normX * math.pi * 2) * (railHeight / 12)
            if botPreset == 4: return 0 if normX < 0.3 or normX > 0.7 else -railHeight / 5
            if botPreset == 5: return math.sin(normX * math.pi) * (-railHeight / 3)
            return 0

        # === Generate Trimmed Rail Sketch ===
        sketch = root.sketches.add(railPlane)
        sketch.name = 'TrimmedRailSketch'

        k = 0.7
        numDivs = k * maxWidth * (1 + railHeight / 100)
        divisions = round(numDivs)
        dy = railHeight / divisions
        shrink = shellThickness * 0.05

        # === Cut Ratio Logic ===
        splineRatio = 0.0833
        cutRatio = 1 - 2 * (splineRatio * railHeight / ribThickness)
        cutDepth = (ribThickness * cutRatio) / 2

        points = []
        totalLength = 0.0
        lastPoint = None

        for j in range(divisions + 1):
            y_local = j * dy
            y_norm = y_local / railHeight
            x = xHalf * railFunc(y_norm)
            normX = x / xHalf if xHalf != 0 else 0

            # Apply deck or bottom rocker offset
            if y_local > railHeight / 2:
                y = y_local + deckRockerOffset(x, normX)
            else:
                y = y_local + bottomRockerOffset(x, normX)

            y -= railHeight / 2

            # Apply uniform shell shrink inward
            mag = math.hypot(x, y)
            fx = x - (shrink * x / mag) if mag != 0 else x
            fy = y - (shrink * y / mag) if mag != 0 else y

            point = adsk.core.Point3D.create(fx, fy, 0)

            # Check cumulative arc length
            if lastPoint:
                cutLength = math.hypot(fx - lastPoint.x, fy - lastPoint.y)
                totalLength += cutLength
                if totalLength > cutDepth:
                    break

            points.append(point)
            lastPoint = point

        # === Create Sketch Curve ===
        if len(points) >= 2:
            pointCol = adsk.core.ObjectCollection.create()
            for pt in points:
                pointCol.add(pt)
            sketch.sketchCurves.sketchFittedSplines.add(pointCol)

        ui.messageBox("✅ Trimmed & embedded rail profile sketch created at midpoint.")

    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
