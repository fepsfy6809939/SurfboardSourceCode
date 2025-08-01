import adsk.core, adsk.fusion, adsk.cam, traceback
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
        maxWidth = getParam('MaxWidth')
        shapeType = int(getParam('BoardPreset') or 0)
        rockerNose = getParam('RockerNose')
        rockerTail = getParam('RockerTail')
        rockerMidOffset = getParam('RockerMidOffset')
        useStagedRocker = getParam('UseStagedRocker') or 0
        segmentLength = getParam('MinSegmentLength')

        if None in [boardLength, maxWidth, rockerNose, rockerTail, rockerMidOffset, useStagedRocker, segmentLength]:
            ui.messageBox("❌ Missing one or more required parameters.")
            return

        if segmentLength <= 0:
            ui.messageBox("❌ MinSegmentLength must be greater than 0.")
            return

        # === Create sketch on XZ plane ===
        xzPlane = root.xZConstructionPlane
        sketch = root.sketches.add(xzPlane)
        sketch.name = 'BoardPlanShape'

        # === Shape functions for board outline ===
        def parabolic(t):
            t = (t - 0.5) * 2
            return 1 - t**2

        def step_tail(t):
            return (1 - (1 - t)**2) * (1 - 0.3 * math.sin(5 * math.pi * (1 - t)))

        def fish_tail(t):
            bump = 0.1 * math.sin(4 * math.pi * (1 - t)) if t < 0.7 else 0
            return (1 - (t - 0.5)**2) + bump

        shapeFuncs = [parabolic, step_tail, fish_tail]
        shapeNames = ['Parabolic', 'StepTail', 'FishTail']
        shapeFunc = shapeFuncs[min(shapeType, len(shapeFuncs) - 1)]
        shapeName = shapeNames[min(shapeType, len(shapeNames) - 1)]

        # === Rocker function logic ===
        if useStagedRocker:
            centerZ = (boardLength / 2.0) + rockerMidOffset
            flatWidth = boardLength / 3.0

            # Ensure flat region is within board
            flatStart = max(0, centerZ - (flatWidth / 2))
            flatEnd = min(boardLength, centerZ + (flatWidth / 2))

            def getRockerY(z):
                if z < flatStart:
                    # Tail curve: concave down to 0 at flatStart
                    t = z / flatStart
                    return -rockerTail * (1 - t) ** 2
                elif z > flatEnd:
                    # Nose curve: concave down to 0 at flatEnd
                    t = (z - flatEnd) / (boardLength - flatEnd)
                    return -rockerNose * t ** 2
                else:
                    return 0  # Flat mid region
        else:
            # Parabolic rocker using 3-point curve through nose-mid-tail
            midZ = (boardLength / 2.0) + rockerMidOffset

            def solve_parabola(z0, y0, z1, y1, z2, y2):
                denom = (z0 - z1) * (z0 - z2) * (z1 - z2)
                a = (z2 * (y1 - y0) + z1 * (y0 - y2) + z0 * (y2 - y1)) / denom
                b = (z2**2 * (y0 - y1) + z1**2 * (y2 - y0) + z0**2 * (y1 - y2)) / denom
                c = (z1 * z2 * (z1 - z2) * y0 + z2 * z0 * (z2 - z0) * y1 + z0 * z1 * (z0 - z1) * y2) / denom
                return a, b, c

            a, b, c = solve_parabola(0, rockerNose, midZ, 0, boardLength, rockerTail)

            def getRockerY(z):
                return a * z**2 + b * z + c

        # === Generate curve points ===
        numPoints = int(math.ceil(boardLength / segmentLength)) + 1
        dz = boardLength / (numPoints - 1)
        points = []

        for i in range(numPoints):
            z = i * dz
            z_norm = z / boardLength
            x = maxWidth * shapeFunc(z_norm)
            y = getRockerY(z)
            pt = adsk.core.Point3D.create(x, y, z)
            points.append(pt)
            sketch.sketchPoints.add(pt)

        # === Draw spline through points ===
        pointCollection = adsk.core.ObjectCollection.create()
        for pt in points:
            pointCollection.add(pt)
        sketch.sketchCurves.sketchFittedSplines.add(pointCollection)

        rockerLabel = 'staged (concave)' if useStagedRocker else 'parabolic'
        ui.messageBox(f"✅ {shapeName} board with {rockerLabel} rocker created.")

    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
