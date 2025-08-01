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

        boardLength     = getParam('BoardLength')
        railHeight      = getParam('MaxThickness')
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

        # === Rocker function ===
        if useStagedRocker:
            centerZ = (boardLength / 2.0) + rockerMidOffset
            flatWidth = boardLength / 3.0
            flatStart = max(0, centerZ - (flatWidth / 2))
            flatEnd = min(boardLength, centerZ + (flatWidth / 2))

            def getRockerY(z):
                if z < flatStart:
                    t = z / flatStart
                    return -rockerTail * (1 - t)**2
                elif z > flatEnd:
                    t = (z - flatEnd) / (boardLength - flatEnd)
                    return -rockerNose * t**2
                else:
                    return 0
        else:
            midZ = (boardLength / 2.0) + rockerMidOffset

            def solve_parabola(z0, y0, z1, y1, z2, y2):
                denom = (z0 - z1) * (z0 - z2) * (z1 - z2)
                a = (z2*(y1 - y0) + z1*(y0 - y2) + z0*(y2 - y1)) / denom
                b = (z2**2*(y0 - y1) + z1**2*(y2 - y0) + z0**2*(y1 - y2)) / denom
                c = (z1*z2*(z1 - z2)*y0 + z2*z0*(z2 - z0)*y1 + z0*z1*(z0 - z1)*y2) / denom
                return a, b, c

            a, b, c = solve_parabola(0, rockerNose, midZ, 0, boardLength, rockerTail)
            def getRockerY(z): return a * z**2 + b * z + c

        # === Reference Sketch ===
        planSketch = next((s for s in root.sketches if s.name == 'BoardPlanShape'), None)
        if not planSketch:
            ui.messageBox("❌ Sketch 'BoardPlanShape' not found.")
            return
        bodyPoints = [pt.geometry for spline in planSketch.sketchCurves.sketchFittedSplines for pt in spline.fitPoints]
        if len(bodyPoints) < 2:
            ui.messageBox("❌ Not enough points in 'BoardPlanShape'.")
            return

        # === Rocker spline (XZ) ===
        xzPlane = root.xZConstructionPlane
        rockerSketch = root.sketches.add(xzPlane)
        rockerSketch.name = 'CenterRib_XZ'
        rockerPoints = []
        for i in range(51):
            z = i * boardLength / 50
            y = getRockerY(z)
            rockerPoints.append(adsk.core.Point3D.create(0, y, z))
        rockerCol = adsk.core.ObjectCollection.create()
        for pt in rockerPoints: rockerCol.add(pt)
        rockerSpline = rockerSketch.sketchCurves.sketchFittedSplines.add(rockerCol)

        # === Construction Plane for Rib ===
        zMid = boardLength / 2
        planeInput = root.constructionPlanes.createInput()
        planeInput.setByOffset(xzPlane, adsk.core.ValueInput.createByReal(zMid))
        railPlane = root.constructionPlanes.add(planeInput)
        railPlane.name = 'TrimmedRailPlane'

        closestPt = min(bodyPoints, key=lambda pt: abs(pt.z - zMid))
        xHalf = abs(closestPt.x)
        yCenter = closestPt.y

        # === Rail shape functions ===
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

        # === Generate Rail Profile ===
        sketch = root.sketches.add(railPlane)
        sketch.name = 'TrimmedRailSketch'
        divisions = round(0.7 * maxWidth * 10 * (1 + (railHeight * 10) / 100))
        dy = railHeight / divisions
        shrink = shellThickness * 0.05
        splineRatio = 0.0833
        cutRatio = 1 - 2 * (splineRatio * railHeight / ribThickness)
        cutDepth = (ribThickness * cutRatio) / 2
        topPoints, bottomPoints = [], []

        for edgeName, pointList, reverse in [('top', topPoints, True), ('bottom', bottomPoints, False)]:
            totalLength = 0.0
            lastPoint = None
            iter_range = reversed(range(divisions + 1)) if reverse else range(divisions + 1)
            for j in iter_range:
                y_local = j * dy
                y_norm = y_local / railHeight
                x = xHalf * railFunc(y_norm)
                normX = x / xHalf if xHalf != 0 else 0
                if y_local > railHeight / 2:
                    y = y_local + deckRockerOffset(x, normX)
                else:
                    y = y_local + bottomRockerOffset(x, normX)
                y -= railHeight / 2
                mag = math.hypot(x, y)
                fx = x - (shrink * x / mag) if mag != 0 else x
                fy = y - (shrink * y / mag) if mag != 0 else y
                pt = adsk.core.Point3D.create(fx, fy, 0)

                if lastPoint:
                    segLength = math.hypot(fx - lastPoint.x, fy - lastPoint.y)
                    totalLength += segLength
                    if totalLength > cutDepth:
                        break
                pointList.append(pt)
                lastPoint = pt

        # === Draw Edge Splines and Mirrors ===
        for pts in [topPoints, bottomPoints]:
            if len(pts) >= 2:
                pc = adsk.core.ObjectCollection.create()
                for p in pts: pc.add(p)
                sketch.sketchCurves.sketchFittedSplines.add(pc)

        mirrorTopPoints = [adsk.core.Point3D.create(-pt.x, pt.y, 0) for pt in reversed(topPoints)]
        mirrorBottomPoints = [adsk.core.Point3D.create(-pt.x, pt.y, 0) for pt in bottomPoints]

        for pts in [mirrorTopPoints, mirrorBottomPoints]:
            if len(pts) >= 2:
                pc = adsk.core.ObjectCollection.create()
                for p in pts: pc.add(p)
                sketch.sketchCurves.sketchFittedSplines.add(pc)

        # === Join arcs ===
        if topPoints and bottomPoints:
            pt_top = topPoints[-1]
            pt_bot = bottomPoints[-1]
            mid_x = ribThickness / 2
            mid_y = (pt_top.y + pt_bot.y) / 2
            arcCol = adsk.core.ObjectCollection.create()
            arcCol.add(pt_bot)
            arcCol.add(adsk.core.Point3D.create(mid_x, mid_y, pt_top.z))
            arcCol.add(pt_top)
            sketch.sketchCurves.sketchFittedSplines.add(arcCol)

        if mirrorTopPoints and mirrorBottomPoints:
            pt_top_m = mirrorTopPoints[0]
            pt_bot_m = mirrorBottomPoints[-1]
            mid_x_m = -ribThickness / 2
            mid_y_m = (pt_top_m.y + pt_bot_m.y) / 2
            arcCol_m = adsk.core.ObjectCollection.create()
            arcCol_m.add(pt_bot_m)
            arcCol_m.add(adsk.core.Point3D.create(mid_x_m, mid_y_m, pt_top_m.z))
            arcCol_m.add(pt_top_m)
            sketch.sketchCurves.sketchFittedSplines.add(arcCol_m)

        # === Sweep ===
        if not sketch.profiles.count:
            ui.messageBox('❌ No profile in TrimmedRailSketch')
            return

        profile = sketch.profiles[0]

        # ✅ Your fixed sweep path logic
        pathCol = adsk.core.ObjectCollection.create()
        pathCol.add(rockerSpline)
        sweepPath = root.features.createPath(pathCol)

        sweeps = root.features.sweepFeatures
        sweepInput = sweeps.createInput(profile, sweepPath, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
        sweepInput.orientation = adsk.fusion.SweepOrientationTypes.PerpendicularOrientationType
        sweeps.add(sweepInput)

        ui.messageBox("✅ Central rib sweep complete.")

    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
