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
        railStyle = int(getParam('RailStyle') or 0)
        midBias = getParam('RailMidBias')
        deckPreset = int(getParam('DeckRockerPreset') or 0)
        botPreset = int(getParam('BotRockerPreset') or 0)
        shellThickness = getParam('ShellThickness')
        railHeight = getParam('MaxThickness')
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

        pointCollection = adsk.core.ObjectCollection.create()   
        for pt in points:
            pointCollection.add(pt)
        sketch.sketchCurves.sketchFittedSplines.add(pointCollection)


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
            
        # === Generate Rails and Shell Splines ===
        numRibs = int(math.ceil(boardLength / segmentLength))
        dz = boardLength / numRibs
        xzPlane = root.xZConstructionPlane

        for i in range(numRibs + 1):
            z_target = i * dz
        
            # Match board body height at Z
            closestPt = min(bodyPoints, key=lambda pt: abs(pt.z - z_target))
            z_actual = closestPt.z
            x_half = abs(closestPt.x)
            y_center = closestPt.y
            
            sampleCount = 100
            maxWidthT = 0
            maxWidth = 0
            
            for j in range(sampleCount + 1):
                t = j / sampleCount
                x = railFunc(t)   
                if abs(x) > maxWidth:
                    maxWidth = abs(x)
                    maxWidthT = t
            
            y_max_local = maxWidthT * railHeight
            normX = railFunc(maxWidthT)
            if y_max_local > railHeight / 2:
                y_max_local += deckRockerOffset(normX, normX)
            else:
                y_max_local += bottomRockerOffset(normX, normX)
            y_max_local -= railHeight / 2
        
            y_center -= y_max_local - (railHeight / 2)
            
            divisions = 8
            dy = railHeight / divisions
            railPoints = []
            shellPoints = []
            maxX = 0
            maxY = 0
            
            for j in range(divisions + 1):
                y_local = j * dy
                y_norm = y_local / railHeight
                x = x_half * railFunc(y_norm)
                normX = x / x_half if x_half != 0 else 0
            
                y = y_local + deckRockerOffset(x, normX) if y_local > railHeight / 2 else y_local + bottomRockerOffset(x, normX)
                y -= railHeight / 2
        
                railPt = (x, y)
                railPoints.append(railPt)
        
                # Inward offset for shell (normal approx)
                dx = -x / math.hypot(x, y) * shellThickness if x != 0 or y != 0 else 0
                dy_shell = -y / math.hypot(x, y) * shellThickness if x != 0 or y != 0 else 0
                shellPoints.append((x + dx, y + dy_shell))
            
                if abs(x) > abs(maxX): maxX = x
                if y > maxY: maxY = y
            
            y_offset = y_center - maxY
            
            planeInput = root.constructionPlanes.createInput()
            planeInput.setByOffset(xzPlane, adsk.core.ValueInput.createByReal(z_actual))
            railPlane = root.constructionPlanes.add(planeInput)
            railPlane.name = f'RailPlane_{i:02d}'
                
            sketch = root.sketches.add(railPlane)
            sketch.name = f'RailSketch_{i:02d}'
                    
            railCol = adsk.core.ObjectCollection.create()
            shellCol = adsk.core.ObjectCollection.create()
            
            for (x, y), (sx, sy) in zip(railPoints, shellPoints):
                railCol.add(adsk.core.Point3D.create(x, y + y_offset, 0))
                shellCol.add(adsk.core.Point3D.create(sx, sy + y_offset, 0))
                
            sketch.sketchCurves.sketchFittedSplines.add(railCol)
            sketch.sketchCurves.sketchFittedSplines.add(shellCol)
            
            if i == 0 or i == numRibs:
                pt1 = adsk.core.Point3D.create(0, y_center, 0)
                pt2 = adsk.core.Point3D.create(0, y_center, 0)
                sketch.sketchCurves.sketchLines.addByTwoPoints(pt1, pt2)
            
        ui.messageBox("✅ Rail and Outer Shell Splines generated.")
            
    except Exception as e:
        if 'ui' in locals():
            ui.messageBox(f'❌ Script Failed:\n{str(e)}\n\n{traceback.format_exc()}')
