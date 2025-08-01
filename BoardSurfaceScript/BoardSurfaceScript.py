# Full Trimmed Rail Sketch with Mirroring and Closed Profile for Extrusion
# Includes Rocker spline for reference

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
        railHeight      = getParam('MaxThickness')
        maxThickness    = getParam('MaxThickness')
        maxWidth        = getParam('MaxWidth')
        segmentLength   = getParam('MinSegmentLength')
        railStyle       = int(getParam('RailStyle') or 0)
        midBias         = getParam('RailMidBias')
        deckPreset      = int(getParam('DeckRockerPreset') or 0)
        botPreset       = int(getParam('BotRockerPreset') or 0)
        shellThickness  = getParam('ShellThickness')
        ribThickness    = getParam('CenterRibThickness')
        rockerNose      = getParam('RockerNose')
        rockerTail      = getParam('RockerTail')
        rockerMidOffset = getParam('RockerMidOffset')
        useStagedRocker = getParam('UseStagedRocker') or 0

        if None in [boardLength, railHeight, segmentLength, midBias, shellThickness, ribThickness]:
            ui.messageBox("❌ Missing one or more required parameters.")
            return

        # === Rocker Function ===
        if useStagedRocker:
            centerZ = (boardLength / 2.0) + rockerMidOffset
            flatWidth = boardLength / 3.0
            flatStart = max(0, centerZ - (flatWidth / 2))
            flatEnd = min(boardLength, centerZ + (flatWidth / 2))
            def getRockerY(z):
                if z < flatStart:
                    t = z / flatStart
                    return -rockerTail * (1 - t) ** 2
                elif z > flatEnd:
                    t = (z - flatEnd) / (boardLength - flatEnd)
                    return -rockerNose * t ** 2
                else:
                    return 0
        else:
            midZ = (boardLength / 2.0) + rockerMidOffset
            def parabola(z0, y0, z1, y1, z2, y2):
                denom = (z0 - z1) * (z0 - z2) * (z1 - z2)
                a = (z2 * (y1 - y0) + z1 * (y0 - y2) + z0 * (y2 - y1)) / denom
                b = (z2**2 * (y0 - y1) + z1**2 * (y2 - y0) + z0**2 * (y1 - y2)) / denom
                c = (z1 * z2 * (z1 - z2) * y0 + z2 * z0 * (z2 - z0) * y1 + z0 * z1 * (z0 - z1) * y2) / denom
                return a, b, c
            a, b, c = parabola(0, rockerNose, midZ, 0, boardLength, rockerTail)
            def getRockerY(z): return a * z**2 + b * z + c

        # === Get Mid Width from Plan Shape ===
        planSketch = next((sk for sk in root.sketches if sk.name == 'BoardPlanShape'), None)
        if not planSketch:
            ui.messageBox("❌ Sketch 'BoardPlanShape' not found.")
            return
        bodyPoints = [pt.geometry for spline in planSketch.sketchCurves.sketchFittedSplines for pt in spline.fitPoints]
        if not bodyPoints:
            ui.messageBox("❌ No points found in 'BoardPlanShape'.")
            return
        midZ = boardLength / 2
        closestPt = min(bodyPoints, key=lambda pt: abs(pt.z - midZ))
        xHalf = abs(closestPt.x)

        # === Construct Central Plane ===
        xzPlane = root.xZConstructionPlane
        planeInput = root.constructionPlanes.createInput()
        planeInput.setByOffset(xzPlane, adsk.core.ValueInput.createByReal(midZ))
        railPlane = root.constructionPlanes.add(planeInput)
        railPlane.name = 'TrimmedRailPlane'

        # === Rocker Profile Sketch ===
        rockerSketch = root.sketches.add(xzPlane)
        rockerSketch.name = 'CenterRib_XZ'
        rockerPoints = [adsk.core.Point3D.create(0, getRockerY(z), z) for z in [i * boardLength / 50 for i in range(51)]]
        rockerCol = adsk.core.ObjectCollection.create()
        for pt in rockerPoints:
            rockerCol.add(pt)
        rockerSketch.sketchCurves.sketchFittedSplines.add(rockerCol)

        # === Rail Bias Profile ===
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

        # === Create Trimmed Rail Sketch ===
        sketch = root.sketches.add(railPlane)
        sketch.name = 'TrimmedRailSketch'
        divisions = int(0.7 * maxWidth * 10 * (1 + maxThickness / 10))
        dy = railHeight / divisions
        shrink = shellThickness * 0.05

        def generateEdgePoints(reverse):
            totalLength, lastPoint = 0.0, None
            points = []
            iter_range = reversed(range(divisions + 1)) if reverse else range(divisions + 1)
            for j in iter_range:
                y_local = j * dy
                y_norm = y_local / railHeight
                x = xHalf * railFunc(y_norm)
                normX = x / xHalf if xHalf != 0 else 0
                y = y_local + (deckRockerOffset(x, normX) if y_local > railHeight/2 else bottomRockerOffset(x, normX))
                y -= railHeight / 2
                mag = math.hypot(x, y)
                fx = x - (shrink * x / mag) if mag else x
                fy = y - (shrink * y / mag) if mag else y
                pt = adsk.core.Point3D.create(fx, fy, 0)
                points.append(pt)
                lastPoint = pt
            return points

        top = generateEdgePoints(True)
        bottom = generateEdgePoints(False)

        def addSpline(points):
            col = adsk.core.ObjectCollection.create()
            for pt in points:
                col.add(pt)
            sketch.sketchCurves.sketchFittedSplines.add(col)

        addSpline(top)
        addSpline(bottom)

        # Join top-bottom with arc
        if top and bottom:
            pt_top, pt_bot = top[-1], bottom[-1]
            mid_x = ribThickness / 2
            mid_y = (pt_top.y + pt_bot.y) / 2
            joinCol = adsk.core.ObjectCollection.create()
            joinCol.add(pt_bot)
            joinCol.add(adsk.core.Point3D.create(mid_x, mid_y, 0))
            joinCol.add(pt_top)
            sketch.sketchCurves.sketchFittedSplines.add(joinCol)

        # === Mirror everything ===
        sketch.isComputeDeferred = True
        for curve in list(sketch.sketchCurves):
            mirrored = adsk.core.ObjectCollection.create()
            for pt in curve.fitPoints:
                mirrored.add(adsk.core.Point3D.create(-pt.geometry.x, pt.geometry.y, pt.geometry.z))
            sketch.sketchCurves.sketchFittedSplines.add(mirrored)

        # Connect start and end lines to close
        sketch.sketchCurves.sketchLines.addByTwoPoints(top[0], bottom[0])
        sketch.sketchCurves.sketchLines.addByTwoPoints(
            adsk.core.Point3D.create(-top[0].x, top[0].y, 0),
            adsk.core.Point3D.create(-bottom[0].x, bottom[0].y, 0)
        )
        sketch.isComputeDeferred = False

        ui.messageBox("✅ Mirrored trimmed rail profile created and ready for extrusion.")

    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
