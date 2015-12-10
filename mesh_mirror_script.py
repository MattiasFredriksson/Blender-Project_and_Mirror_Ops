#  mirror_mesh_script.py (c) 2015 Mattias Fredriksson
#
# ##### BEGIN GPL LICENSE BLOCK #####
#
#  This program is free software: you can redistribute it and/or modify
#  it under the terms of the GNU General Public License as published by
#  the Free Software Foundation, either version 3 of the License, or
#  (at your option) any later version.
#
#  This program is distributed in the hope that it will be useful,
#  but WITHOUT ANY WARRANTY; without even the implied warranty of
#  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#  GNU General Public License for more details.
#
#  You should have received a copy of the GNU General Public License
#  along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# ##### END GPL LICENSE BLOCK #####


import bpy, mathutils, bmesh, time

from queue import Queue
from bpy.props import *
from math import *

bl_info = {
	'name': "Mirror Mesh",
    'author': "Mattias Fredriksson ",
    'version': (0, 9, 0),
    'blender': (2, 70, 0),
    'location': "Objectmode",
    'warning': "Contains settings with long execution time",
    'description': "Mirrors a mesh along the normals of a defined mesh surface. Select the meshes you want to mirror and then make the mirror mesh the active object",
    'wiki_url': "",
    'tracker_url': "",
    'category': 'Mesh'}


largeFloat = 10000000
	
class MirrorMesh(bpy.types.Operator):
	bl_idname = "mesh.mirror_mesh_along_mirrormesh_normals"
	bl_label = "Mirror Mesh"
	bl_info = "Mirrors a mesh along the normals of a defined mesh surface"
	bl_options = {'REGISTER', 'UNDO'}
	
	
	mirrorSmooth = BoolProperty(name = "Smoothed",
            description="If the vertices will be mirrored smoothly over the mirror face or if it will be continous",
			default=True)
	cullBackfaces = BoolProperty(name = "No Backface Intersection",
            description="Vertices is not mirrored on faces facing away from the vertice",
			default=False)
	onlyIntersectingVert = BoolProperty(name = "Intersecting verts only",
            description="Mirror only verts that intersect the mirror mesh",
			default=True)
	intersectClosest = BoolProperty(name = "(Expensive) Closest Intersection",
            description="Forces mirroring of each vertice for the closest face they intersect, might solve problems of two faces intersecting a vertice. May not function as expected as it's not the intended use of the script. Slow on dense meshes.",
			default=False)
	biasValue = FloatProperty(name="Intersection Bias",
            description="Error marginal for intersection tests, can solve intersection problems",
            default=0.0001, min=0.0001, max=0.1)
	
	#Shared Values set from the blender settings since functions call them statically as they are not related to the main class object.
	#May not be the best solution but it works!
	bias = 0.0001
	biasOne = 1+ bias
	biasNeg = -bias
	smoothed = True
	cull = True
	closestOnly = False
	onlyIntersecting = True
	displayExecutionTime = True
	
	def execute(self, context):
		MirrorMesh.bias = self.bias
		MirrorMesh.biasOne = 1 + self.bias
		MirrorMesh.biasNeg = -self.bias
		MirrorMesh.smoothed = self.mirrorSmooth
		MirrorMesh.cull = self.cullBackfaces
		MirrorMesh.closestOnly = self.intersectClosest
		MirrorMesh.onlyIntersecting = self.onlyIntersectingVert
		#Execution timer
		start_time = time.time()

		# Get the active object
		ob_act = bpy.context.active_object
		
		#Validate the active selection object
		if not ob_act or ob_act.type != 'MESH':
				self.report({'ERROR'}, "No mesh selected!")
				return {'CANCELLED'}
			
		if MirrorMesh.displayExecutionTime :
			self.report({'INFO'}, "Executing: mirror_mesh_func")
		
		#We add a temporary modifier to triangulate the faces!
		tmod = ob_act.modifiers.new(name='tmpTriangulate', type='TRIANGULATE')
		tmod.quad_method = 'BEAUTY'
		#We create a bmesh with the modifiers applied and vertices in world space !
		mMesh = createBmesh(ob_act, context.scene, True)
		mMesh.normal_update()
		#Clear tmp modifier
		ob_act.modifiers.remove(tmod)
				
		#Lets mirror the selected meshes (exclude the active mirror mesh!)
		for ob in context.selected_objects : 
			if ob.type == 'MESH' and ob != ob_act :
				#Copy the mesh into a bm mesh!
				mesh = createBmesh(ob)
				
				#Mirror it rawr
				nonMCount = MirrorMesh.mirrorMesh(mesh, mMesh)
				
				#We only create a copy if the 
				if nonMCount < len(mesh.verts) :
					#Cleanup, move it back into it's local space, flip the inverted normals.
					mInv = ob.matrix_world.copy()
					mInv.invert()
					mesh.transform(mInv) 
					flipNormals(mesh)
				
					#Copy it into a new object!
					mirrorOb = createEmptyMeshCopy(ob, "_Mirror", "_MirrorMesh", context)
					# Set the mesh into the object
					mesh.to_mesh(mirrorOb.data)
					if nonMCount != 0 :
						self.report({'WARNING'}, "Mesh: %s has %d vertices that did not intersect the mirror mesh. Validate that all verts intersect the mirror mesh for better result and faster execution" %(ob.name, nonMCount))
				else :
					self.report({'WARNING'}, "Mesh: %s does not intersect the mirror mesh, no mirror created" %ob.name)
				# Free the bm data.
				mesh.free()
		#		
		mMesh.free()
		if MirrorMesh.displayExecutionTime :
			self.report({'INFO'}, "Finished, execution time: %.2f seconds ---" % (time.time() - start_time))
		return {'FINISHED'}
	
	def mirrorMesh(mesh, mirrorMesh):
		
		#create a our search data array
		searchData = [SearchData() for i in range(len(mesh.verts))]
		
		#loop through each vert in the 
		for i in range(len(searchData)):
			if searchData[i].notMirrored():
				#loop through every triangle in the mirror mesh and find the closest "triangle plane" that intersects
				MirrorMesh.findClosestTri(mesh.verts[i], mirrorMesh, searchData)
				mData = searchData[i]._mirrorData
				
				#If we found a intersecting mirror face mirror it!
				if mData is not None and mData._intersected :
					#mirror the vertice
					MirrorMesh.mirrorVert(mesh.verts[i], mData)
					#if we do not itterate on every vert, we search closest intersecting in the mirror mesh!
					if not MirrorMesh.closestOnly :
						MirrorMesh.mirrorConnected(i, mesh, mirrorMesh, searchData)
		
		#We check if some vertices did not get mirrored
		nonMirrorCount = 0
		for i in range(len(searchData)):
			if searchData[i].notMirrored() :
				nonMirrorCount += 1
		#If we have closest only we do not check if we have vertices that do not intersect a triangle but are connected to one that is, 
		#if we have one then we mirror it with the same triangle plane! (If the mirror mesh do not cover the mesh properly this will help in this specific mode)
		if MirrorMesh.closestOnly and not MirrorMesh.onlyIntersecting:
			MirrorMesh.mirrorNonIntersecting(nonMirrorCount, mesh, mirrorMesh, searchData)
		#return non-mirrored count
		return nonMirrorCount
			
	def mirrorNonIntersecting(nonMirrorCount, mesh, mirrorMesh, searchData) :
		#
		#	Mirrors vertices that is not intersecting a face by using the mirror connected function
		#	(used only when we ClosestOnly setting is enabled)
		#
		
		#If we have one go through all connected vertices of already mirrored vertices and see if it has an unconnected vertice(s)
		if nonMirrorCount > 0 :
			for i in range(len(searchData)):
				if searchData[i].mirrored() :
					MirrorMesh.mirrorConnected(i, mesh, mirrorMesh, searchData, False)
				
	def mirrorVert(vert, mirrorData, forceFlatMirror = False):
		
		if not MirrorMesh.smoothed or forceFlatMirror :
			mVec = mirrorData.calcFlatMirrorVector()
		else :
			mVec = mirrorData.calcSmoothMirrorVector()
		#Move the vertice 
		vert.co = vert.co + mVec 
	
	def mirrorConnected(initVertInd, mesh, mirrorMesh, searchData, intersectionTest = True) :
		#
		#	Itterates through all connected verts and mirror them by taking the first intersecting mirror face.
		#	The first intersecting face is found by taking the mirror face of the closest connected vertex (that has been mirrored)
		#	If we do not want to check intersection the function mirrors the verts along the same face as the last connected vertex
		#
	
		vertQueue = Queue()
		MirrorMesh.queueConnectedVerts(mesh.verts[initVertInd], searchData, vertQueue)
		
		while not vertQueue.empty() :
			vert = vertQueue.get_nowait()
			i = vert.index
			
			#We need to check that the vert has not already been mirrored again, queueConnected does this but it does not check for duplicated additions
			if searchData[i].notMirrored():
				mData = None
				#If the function should not search for intersecting data, only mirror verts that has not been mirrored and is connected to a mirrored vert
				
				#Get the mirror face of the closest vert that is mirrored
				closeVert = searchData[i]._closeVert
				lastMData = searchData[closeVert.index]._mirrorData
				
				if intersectionTest :				
					#Check for the first face we intersect (from our last intersecting face)
					MirrorMesh.findFirstTri(vert, lastMData._mirrorTri, mirrorMesh, searchData)
					mData = searchData[i]._mirrorData
				
				if mData is not None and mData._intersected :
					MirrorMesh.mirrorVert(vert, mData)
					#Queue all connected vertices!
					MirrorMesh.queueConnectedVerts(vert, searchData, vertQueue)
				elif not MirrorMesh.onlyIntersecting :
					#If no intersection we mirror along the last mirror face plane
					MirrorMesh.findDistance(vert, lastMData._mirrorTri, searchData)
					mData = searchData[i]._mirrorData
					#MirrorFlat
					MirrorMesh.mirrorVert(vert, mData, True)
					#Queue all connected vertices!
					MirrorMesh.queueConnectedVerts(vert, searchData, vertQueue)
				
				
	def findFirstTri(vert, lastMFace, mirrorMesh, searchData) :
		#
		#	Itterates through all faces in the mirror mesh and tests for intersection, first intersecting adjacent face connected to the initial search face is returned
		#
		
		faceQueue = Queue()
		#Tag keep track on what face we have tested / in queue. False for not tested
		taggedFaces = []
		
		#Start testing from the initial face!
		lastMFace.tag = True
		faceQueue.put_nowait(lastMFace)
		taggedFaces.append(lastMFace)
		
		while not faceQueue.empty() :
			face = faceQueue.get_nowait()
			mDat = MirrorMesh.triIntersection(vert.co, face)
			if mDat is not None and mDat._intersected :
				searchData[vert.index].setMirror(mDat)
				break #we found an intersecting tri
			#Queue connected faces
			MirrorMesh.queueConnectedFaces(face, mirrorMesh, faceQueue, taggedFaces)
		
		for f in taggedFaces :
			f.tag = False

	def findClosestTri(vert, mirrorMesh, searchData) :
		#
		#	Updates the search data with the closest intersecting triangle plane (not closest triangle)
		#
		
		#Searches trough each triangle face in the mirror mesh to find the closest plane where the triangle intersects and updates the search data with it!
		for tri in mirrorMesh.faces :
			mDat = MirrorMesh.triIntersection(vert.co, tri)
			if mDat is not None and mDat._intersected :
				searchData[vert.index].setClosestMirror(mDat)
	
	def findDistance(vert, mTri, searchData) : 
		t = mTri.normal.dot(vert.co - mTri.verts[0].co)
		mDat = MirrorData(mTri, False, t)
		searchData[vert.index].setMirror(mDat)
	
		
	def triIntersection(vertCo, mTri):
		
		#distance between tri plane and vert
		t = mTri.normal.dot(vertCo-mTri.verts[0].co)
		
		#If we dont mirror verts behind the face
		if MirrorMesh.cull and t < 0 :
			return None
		
		#We find the three points along the normal of the triangle vertices which spans the plane which our vertice is contained in
		p0 = t / mTri.normal.dot(mTri.verts[0].normal) * mTri.verts[0].normal + mTri.verts[0].co
		p1 = t / mTri.normal.dot(mTri.verts[1].normal) * mTri.verts[1].normal + mTri.verts[1].co
		p2 = t / mTri.normal.dot(mTri.verts[2].normal) * mTri.verts[2].normal + mTri.verts[2].co
		
		v0 = p1-p0
		v1 = p2-p0
		v2 = vertCo - p0
		
		d00 = v0.dot(v0)
		d01 = v0.dot(v1)
		d11 = v1.dot(v1)
		d20 = v2.dot(v0)
		d21 = v2.dot(v1)
		
		invDenom = 1.0 / (d00 * d11 - d01 * d01)
		
		v = (d11 * d20 - d01 * d21) * invDenom
		w = (d00 * d21 - d01 * d20) * invDenom
		u = 1.0 - v - w
		return MirrorData(mTri, u > MirrorMesh.biasNeg and v > MirrorMesh.biasNeg and w > MirrorMesh.biasNeg, t, u,v,w)
	
	def queueConnectedVerts(vert, searchData, queue) :
		
		for edge in vert.link_edges :
			connected = edge.other_vert(vert)
			data = searchData[connected.index]
			#If the mirror
			if data.notMirrored() :
				queue.put_nowait(connected)
				#The closest connected vert !that already is mirrored!, is stored in the search data
				distance = (vert.co - connected.co).length
				if distance < data._closeDistance :
					data._closeDistance = distance
					data._closeVert = vert
					
	def queueConnectedFaces(face, mMesh, queue, tagList) :
		#
		#	Adds adjacent faces of the specified face to the queue, if they are not already tested / in queue
		#
		
		for edge in face.edges :
			for otherFace in edge.link_faces :
				if not otherFace.tag :
					queue.put_nowait(otherFace)
					otherFace.tag = True
					tagList.append(otherFace)
					
	
def createBmesh(ob, scene = None, applyModifiers = False) :

	bm = bmesh.new()
	
	if ob.type == 'MESH' :
		if applyModifiers and scene is not None:
			bm.from_object(ob, scene)
		else :
			bm.from_mesh(ob.data)
		bm.transform(ob.matrix_world)
	
		#Some derp functions we need to call to use it:
		bm.verts.ensure_lookup_table()
		bm.edges.ensure_lookup_table()
		bm.faces.ensure_lookup_table()

	return bm
	
def createEmptyMeshCopy(ob, obTag = "_Copy", meshTag = "_CopyMesh", context = None, copyTransform = True):
	
	#Creates a copy of a mesh with relevant data, if the object is not a mesh an empty mesh will be returned.
	
	mesh = bpy.data.meshes.new(ob.name + meshTag) 		# create a new mesh with the name
	newOb = bpy.data.objects.new(ob.name + obTag, mesh)	# create an object with that mesh
	if	copyTransform :
		newOb.matrix_world = ob.matrix_world			# Copy the transformation matrix of the object 

		#If object is not a mesh return the empty
	if ob.type != 'MESH':
		return newOb

	#Copy modifiers
	for mod in ob.modifiers :
		newOb.modifiers.new(mod.name, mod.type)
	# Link object to the scene
	if context is not None :
		context.scene.objects.link(newOb)         						
	return newOb

def flipNormals(bmesh):
	for face in bmesh.faces :
		face.normal_flip()
	
# Register the operator

def register():
	bpy.utils.register_class(MirrorMesh)


def unregister():
	bpy.utils.unregister_class(MirrorMesh)

if __name__ == "__main__":
		register()
		
		
class SearchData:

#Stores data for each vertice to keep track on relation between the mesh and the mirror mesh

	def __init__(self):#initiate class with params
		self._closeDistance = largeFloat
		self._closeVert = None
		self._mirrorData = None
		
	def mirrored(self):
		return self._mirrorData != None
	def notMirrored(self):
		return self._mirrorData == None
	
	def setClosestMirror(self, mirrorData) :
		#Sets mirror data if it's closer then the pre-existing one
		if self._mirrorData == None or mirrorData._t < self._mirrorData._t:
			self._mirrorData = mirrorData
		
	def setMirror(self, mirrorData) :
			self._mirrorData = mirrorData
	
class MirrorData:

#class used to store intersection data towards a triangle in the mirror mesh

	def __init__(self, mirrorTri = None, intersected = False,t = largeFloat, u = 0,v = 0,w = 0, n = mathutils.Vector((0.0,0.0,0.0))):
		self._u = u
		self._v = v
		self._w = w
		self._t = t
		self._n = n
		self._mirrorTri = mirrorTri
		self._intersected = intersected
		
	def calcSmoothMirrorVector(self) :
		norm = self._mirrorTri.verts[0].normal * self._u + self._mirrorTri.verts[1].normal * self._v + self._mirrorTri.verts[2].normal * self._w
		return (-2 * self._t)/self._mirrorTri.normal.dot(norm) * norm
	
	def calcFlatMirrorVector(self) :
		return (-2 * self._t) * self._mirrorTri.normal
		