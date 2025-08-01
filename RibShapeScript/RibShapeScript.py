import adsk.core, adsk.fusion, traceback, math

def run(context):
    try:
        app = adsk.core.Application.get()
        ui = app.userInterface
        design = app.activeProduct
        root = design.rootComponent

        def getParam(name):
            param = design.userParameters.itemByName(name)
            return param.value if param else None

        # Parameters
        boardLength = getParam('BoardLength')
        maxWidth = getParam('MaxWidth')
        rockerNose = getParam('RockerNose')
        rockerTail = getParam('RockerTail')
        rockerMidOffset = getParam('RockerMidOffset')
        useStagedRocker = getParam('UseStagedRocker') or 0
        railStyle = int(getParam('RailStyle') or 0)
        midBias = getParam('RailMidBias')
        deckPreset = int(getParam('DeckRockerPreset') or 0)
        botPreset = int(getParam('BotRockerPreset') or 0)
        shellThickness = getParam('ShellThickness')
        railHeight = getParam('MaxThickness')
        ribSpacing = getParam('RibSpacing')
        boardPreset = int(getParam('BoardPreset') or 0)

        if None in [boardLength, maxWidth, rockerNose, rockerTail, rockerMidOffset, ribSpacing]:
            ui.messageBox("❌ Missing one or more required parameters.")
            return

        # === Board shape function ===
        def shapeFunc_factory(preset):
            if preset == 0:
                return lambda t: 1 - ((t - 0.5) * 2) ** 2  # Parabolic
            elif preset == 1:
                return lambda t: (1 - (1 - t)**2) * (1 - 0.3 * math.sin(5 * math.pi * (1 - t)))  # Step tail
            elif preset == 2:
                return lambda t: (1 - (t - 0.5)**2) + (0.1 * math.sin(4 * math.pi * (1 - t)) if t < 0.7 else 0)  # Fish
            return lambda t: 1 - ((t - 0.5) * 2) ** 2

        shapeFunc = shapeFunc_factory(boardPreset)

        # === Rocker profile ===
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

            def solve_parabola(z0, y0, z1, y1, z2, y2):
                denom = (z0 - z1) * (z0 - z2) * (z1 - z2)
                a = (z2 * (y1 - y0) + z1 * (y0 - z2) + z0 * (y2 - y1)) / denom
                b = (z2**2 * (y0 - y1) + z1**2 * (y2 - y0) + z0**2 * (y1 - y2)) / denom
                c = (z1 * z2 * (z1 - z2) * y0 + z2 * z0 * (z2 - z0) * y1 + z0 * z1 * (z0 - z1) * y2) / denom
                return a, b, c

            a, b, c = solve_parabola(0, rockerNose, midZ, 0, boardLength, rockerTail)

            def getRockerY(z):
                return a * z**2 + b * z + c

        # === Rail shaping ===
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

        # === Generate Ribs ===
        numRibs = max(3, int(boardLength / ribSpacing))
        if numRibs % 2 == 0:
            numRibs += 1
        dz = boardLength / (numRibs - 1)

        for i in range(numRibs):
            z = i * dz
            centerZ = boardLength / 2 + rockerMidOffset
            flatStart = max(0, centerZ - boardLength / 6)
            flatEnd = min(boardLength, centerZ + boardLength / 6)

            if z < flatStart:
                t = z / flatStart
                taper = 0.5 + 0.5 * t ** 2
            elif z > flatEnd:
                t = (boardLength - z) / (boardLength - flatEnd)
                taper = 0.5 + 0.5 * t ** 2
            else:
                taper = 1.0

            z_norm = z / boardLength
            localHalfWidth = maxWidth * shapeFunc(z_norm)
            width = localHalfWidth * 2 * taper

            if width < 0.1 * maxWidth:
                continue

            x_half = width / 2

            railPoints = []
            divisions = 16
            for j in range(divisions + 1):
                t = j / divisions
                x = x_half * railFunc(t)
                normX = x / x_half if x_half != 0 else 0
                y = t * railHeight
                y += deckRockerOffset(x, normX) if t > 0.5 else bottomRockerOffset(x, normX)
                y -= railHeight * midBias
                railPoints.append(adsk.core.Point3D.create(x, y, 0))

            fullPoints = railPoints + [adsk.core.Point3D.create(-p.x, p.y, 0) for p in reversed(railPoints)]

            # === Create rib sketch plane ===
            xzPlane = root.xZConstructionPlane
            planeInput = root.constructionPlanes.createInput()
            planeInput.setByOffset(xzPlane, adsk.core.ValueInput.createByReal(z))
            ribPlane = root.constructionPlanes.add(planeInput)
            ribPlane.name = f'RibPlane_{i:02d}'

            rockerY = getRockerY(z)
            shellInset = 0.95 * shellThickness

            adjustedPoints = []
            for pt in fullPoints:
                xOffset = -shellInset if pt.x > 0 else shellInset if pt.x < 0 else 0
                adjustedPt = adsk.core.Point3D.create(pt.x + xOffset, pt.y + rockerY, pt.z)
                adjustedPoints.append(adjustedPt)

            sketch = root.sketches.add(ribPlane)
            sketch.name = f'RibSketch_{i:02d}'
            pointCol = adsk.core.ObjectCollection.create()
            for pt in adjustedPoints:
                pointCol.add(pt)
            sketch.sketchCurves.sketchFittedSplines.add(pointCol)

            # === Extrude if rib thickness defined ===
            ribThickness = getParam('RibThickness')
            if ribThickness:
                prof = None
                maxArea = 0
                for p in sketch.profiles:
                    areaProps = p.areaProperties(adsk.fusion.CalculationAccuracy.MediumCalculationAccuracy)
                    if areaProps.area > maxArea:
                        maxArea = areaProps.area
                        prof = p
                if prof:
                    extrudes = root.features.extrudeFeatures
                    extInput = extrudes.createInput(prof, adsk.fusion.FeatureOperations.NewBodyFeatureOperation)
                    distance = adsk.core.ValueInput.createByReal(ribThickness / 2)
                    extInput.setSymmetricExtent(distance, True)
                    extrudes.add(extInput)

        ui.messageBox("✅ Rib sketches generated with curvature and tapering.")

    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Rib Sketch Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
