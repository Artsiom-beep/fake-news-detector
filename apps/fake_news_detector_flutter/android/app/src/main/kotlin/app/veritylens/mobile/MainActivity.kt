package app.veritylens.mobile

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ContentUris
import android.content.Intent
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.util.Size
import android.webkit.MimeTypeMap
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel
import java.io.ByteArrayOutputStream

class MainActivity : FlutterActivity() {
    private val channelName = "app.veritylens.mobile/original_image_picker"
    private val pickOriginalImageRequest = 4201
    private val permissionRequest = 4202
    private val androidExportedNamePattern =
        Regex("""^JPEG_(\d{8})_(\d{6})[_-].*\.jpe?g$""", RegexOption.IGNORE_CASE)

    private enum class PendingAction {
        PICK_IMAGE,
        LATEST_CAMERA,
        LIST_CAMERA,
        LOAD_CAMERA
    }

    private var pendingPickResult: MethodChannel.Result? = null
    private var pendingAction: PendingAction? = null
    private var pendingListLimit = 80
    private var pendingLoadId: Long? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            when (call.method) {
                "pickOriginalImage" -> pickOriginalImage(result)
                "pickLatestCameraImage" -> pickLatestCameraImage(result)
                "listCameraImages" -> listCameraImages(result, call.argument<Int>("limit") ?: 80)
                "loadCameraImage" -> loadCameraImage(
                    result,
                    (call.argument<Number>("id"))?.toLong()
                )
                else -> result.notImplemented()
            }
        }
    }

    private fun pickOriginalImage(result: MethodChannel.Result) {
        if (!startPending(result)) {
            return
        }
        val permissions = missingPermissions(needsImageReadPermission = true)
        if (permissions.isNotEmpty()) {
            pendingAction = PendingAction.PICK_IMAGE
            requestPermissions(permissions, permissionRequest)
            return
        }
        launchOriginalImagePicker()
    }

    private fun pickLatestCameraImage(result: MethodChannel.Result) {
        if (!startPending(result)) {
            return
        }
        val permissions = missingPermissions(needsImageReadPermission = true)
        if (permissions.isNotEmpty()) {
            pendingAction = PendingAction.LATEST_CAMERA
            requestPermissions(permissions, permissionRequest)
            return
        }
        loadLatestCameraImage()
    }

    private fun listCameraImages(result: MethodChannel.Result, limit: Int) {
        if (!startPending(result)) {
            return
        }
        val permissions = missingPermissions(needsImageReadPermission = true)
        if (permissions.isNotEmpty()) {
            pendingAction = PendingAction.LIST_CAMERA
            pendingListLimit = limit
            requestPermissions(permissions, permissionRequest)
            return
        }
        completePick(queryCameraImageItems(limit))
    }

    private fun loadCameraImage(result: MethodChannel.Result, id: Long?) {
        if (id == null) {
            result.error("missing_id", "Image id is required.", null)
            return
        }
        if (!startPending(result)) {
            return
        }
        val permissions = missingPermissions(needsImageReadPermission = true)
        if (permissions.isNotEmpty()) {
            pendingAction = PendingAction.LOAD_CAMERA
            pendingLoadId = id
            requestPermissions(permissions, permissionRequest)
            return
        }
        loadCameraImageById(id)
    }

    private fun startPending(result: MethodChannel.Result): Boolean {
        if (pendingPickResult != null) {
            result.error("busy", "An image picker is already open.", null)
            return false
        }
        pendingPickResult = result
        return true
    }

    private fun missingPermissions(needsImageReadPermission: Boolean): Array<String> {
        val permissions = mutableListOf<String>()
        if (needsImageReadPermission && !hasImageReadPermission()) {
            if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
                permissions.add(Manifest.permission.READ_MEDIA_IMAGES)
            } else if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.M) {
                permissions.add(Manifest.permission.READ_EXTERNAL_STORAGE)
            }
        }
        if (
            Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q &&
            checkSelfPermission(Manifest.permission.ACCESS_MEDIA_LOCATION) != PackageManager.PERMISSION_GRANTED
        ) {
            permissions.add(Manifest.permission.ACCESS_MEDIA_LOCATION)
        }
        return permissions.toTypedArray()
    }

    private fun hasImageReadPermission(): Boolean {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.M) {
            return true
        }
        return if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU) {
            checkSelfPermission(Manifest.permission.READ_MEDIA_IMAGES) == PackageManager.PERMISSION_GRANTED
        } else {
            checkSelfPermission(Manifest.permission.READ_EXTERNAL_STORAGE) == PackageManager.PERMISSION_GRANTED
        }
    }

    private fun launchOriginalImagePicker() {
        launchFileImagePicker()
    }

    private fun openFileIntent(action: String, forceDocumentsUi: Boolean = false): Intent {
        return Intent(action).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "*/*"
            putExtra(Intent.EXTRA_ALLOW_MULTIPLE, false)
            putExtra("android.content.extra.SHOW_ADVANCED", true)
            if (forceDocumentsUi) {
                setPackage("com.google.android.documentsui")
            }
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            if (action == Intent.ACTION_OPEN_DOCUMENT) {
                addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
            }
        }
    }

    private fun launchFileImagePicker() {
        try {
            startActivityForResult(
                openFileIntent(Intent.ACTION_OPEN_DOCUMENT, forceDocumentsUi = true),
                pickOriginalImageRequest
            )
        } catch (_: ActivityNotFoundException) {
            try {
                startActivityForResult(openFileIntent(Intent.ACTION_OPEN_DOCUMENT), pickOriginalImageRequest)
            } catch (_: ActivityNotFoundException) {
                startActivityForResult(openFileIntent(Intent.ACTION_GET_CONTENT), pickOriginalImageRequest)
            }
        } catch (_: SecurityException) {
            startActivityForResult(openFileIntent(Intent.ACTION_OPEN_DOCUMENT), pickOriginalImageRequest)
        }
    }

    override fun onRequestPermissionsResult(
        requestCode: Int,
        permissions: Array<out String>,
        grantResults: IntArray
    ) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode != permissionRequest) {
            return
        }
        when (pendingAction) {
            PendingAction.PICK_IMAGE -> launchOriginalImagePicker()
            PendingAction.LATEST_CAMERA -> {
                if (hasImageReadPermission()) {
                    loadLatestCameraImage()
                } else {
                    completePickError(
                        "permission_denied",
                        "Photo permission is required to read the original camera file."
                    )
                }
            }
            PendingAction.LIST_CAMERA -> {
                if (hasImageReadPermission()) {
                    completePick(queryCameraImageItems(pendingListLimit))
                } else {
                    completePickError(
                        "permission_denied",
                        "Photo permission is required to list original camera files."
                    )
                }
            }
            PendingAction.LOAD_CAMERA -> {
                val id = pendingLoadId
                if (hasImageReadPermission() && id != null) {
                    loadCameraImageById(id)
                } else {
                    completePickError(
                        "permission_denied",
                        "Photo permission is required to read the original camera file."
                    )
                }
                pendingLoadId = null
            }
            null -> Unit
        }
        pendingAction = null
    }

    override fun onActivityResult(requestCode: Int, resultCode: Int, data: Intent?) {
        if (requestCode != pickOriginalImageRequest) {
            super.onActivityResult(requestCode, resultCode, data)
            return
        }

        if (resultCode != Activity.RESULT_OK || data?.data == null) {
            completePick(null)
            return
        }

        val uri = data.data!!
        try {
            if ((data.flags and Intent.FLAG_GRANT_READ_URI_PERMISSION) != 0) {
                try {
                    contentResolver.takePersistableUriPermission(
                        uri,
                        Intent.FLAG_GRANT_READ_URI_PERMISSION
                    )
                } catch (_: SecurityException) {
                    // Some providers grant temporary access only, which is enough for this read.
                }
            }

            val selectedName = displayName(uri)
            val cameraTwin =
                if (hasImageReadPermission()) queryCameraTwinForExportedName(selectedName) else null
            val targetUri = cameraTwin?.uri ?: uri
            var targetName = cameraTwin?.name ?: selectedName
            var targetMimeType = cameraTwin?.mimeType ?: (contentResolver.getType(uri) ?: "")
            if (!isSupportedImageFile(targetName, targetMimeType)) {
                completePickError("unsupported_file", "Choose an image file: JPEG, PNG, WebP, BMP, or TIFF.")
                return
            }
            val originalUri = originalMediaUri(targetUri)
            var bytes = readUriBytes(originalUri) ?: readUriBytes(targetUri)
            if (bytes == null && cameraTwin != null) {
                bytes = readUriBytes(uri)
                targetName = selectedName
                targetMimeType = contentResolver.getType(uri) ?: ""
            }
            if (bytes == null) {
                completePickError("read_failed", "Could not read the selected image.")
                return
            }

            completePick(
                mapOf(
                    "name" to targetName,
                    "bytes" to bytes,
                    "mimeType" to targetMimeType,
                    "usedOriginalUri" to (originalUri != uri),
                    "source" to if (cameraTwin != null) "matched_camera_original" else "selected_image",
                    "context" to if (cameraTwin != null) {
                        mediaContext(cameraTwin, "matched_camera_original", originalUri != uri)
                    } else {
                        selectedUriContext(uri, selectedName, targetMimeType, originalUri != uri)
                    }
                )
            )
        } catch (error: Exception) {
            completePickError("pick_failed", error.message ?: "Could not open the selected image.")
        }
    }

    private fun loadLatestCameraImage() {
        try {
            val media = queryLatestImage(cameraOnly = true) ?: queryLatestImage(cameraOnly = false)
            if (media == null) {
                completePickError("not_found", "No camera photo was found on this phone.")
                return
            }

            val originalUri = originalMediaUri(media.uri)
            val bytes = readUriBytes(originalUri) ?: readUriBytes(media.uri)
            if (bytes == null) {
                completePickError("read_failed", "Could not read the latest camera photo.")
                return
            }

            completePick(
                mapOf(
                    "name" to media.name,
                    "bytes" to bytes,
                    "mimeType" to media.mimeType,
                    "usedOriginalUri" to (originalUri != media.uri),
                    "source" to "latest_camera",
                    "context" to mediaContext(media, "latest_camera", originalUri != media.uri)
                )
            )
        } catch (error: Exception) {
            completePickError("latest_camera_failed", error.message ?: "Could not load the latest camera photo.")
        }
    }

    private data class MediaItem(
        val id: Long,
        val uri: Uri,
        val name: String,
        val mimeType: String,
        val dateTaken: Long,
        val dateAdded: Long,
        val sizeBytes: Long,
        val width: Int,
        val height: Int,
        val relativePath: String,
        val bucketName: String
    )

    private fun queryLatestImage(cameraOnly: Boolean): MediaItem? {
        val selectionParts = mutableListOf("${MediaStore.Images.Media.MIME_TYPE} = ?")
        val selectionArgs = mutableListOf("image/jpeg")
        if (cameraOnly && Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            selectionParts.add("${MediaStore.Images.Media.RELATIVE_PATH} LIKE ?")
            selectionArgs.add("%DCIM/Camera%")
        }

        val sortOrder =
            "${MediaStore.Images.Media.DATE_TAKEN} DESC, ${MediaStore.Images.Media.DATE_ADDED} DESC"
        contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            imageProjection(),
            selectionParts.joinToString(" AND "),
            selectionArgs.toTypedArray(),
            sortOrder
        )?.use { cursor ->
            if (!cursor.moveToFirst()) {
                return null
            }
            return mediaItemFromCursor(cursor)
        }
        return null
    }

    private fun queryCameraImageItems(limit: Int): List<Map<String, Any?>> {
        val safeLimit = limit.coerceIn(1, 120)
        val items = mutableListOf<Map<String, Any?>>()
        contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            imageProjection(),
            cameraImageSelection(),
            cameraImageSelectionArgs(),
            "${MediaStore.Images.Media.DATE_TAKEN} DESC, ${MediaStore.Images.Media.DATE_ADDED} DESC"
        )?.use { cursor ->
            while (cursor.moveToNext() && items.size < safeLimit) {
                val media = mediaItemFromCursor(cursor)
                items.add(
                    mapOf(
                        "id" to media.id,
                        "name" to media.name,
                        "mimeType" to media.mimeType,
                        "dateTaken" to media.dateTaken,
                        "dateAdded" to media.dateAdded,
                        "sizeBytes" to media.sizeBytes,
                        "width" to media.width,
                        "height" to media.height,
                        "relativePath" to media.relativePath,
                        "bucketName" to media.bucketName,
                        "thumbnail" to thumbnailBytes(media.uri)
                    )
                )
            }
        }
        return items
    }

    private fun loadCameraImageById(id: Long) {
        try {
            val media = queryImageById(id)
            if (media == null) {
                completePickError("not_found", "The selected camera photo was not found.")
                return
            }
            val originalUri = originalMediaUri(media.uri)
            val bytes = readUriBytes(originalUri) ?: readUriBytes(media.uri)
            if (bytes == null) {
                completePickError("read_failed", "Could not read the selected camera photo.")
                return
            }
            completePick(
                mapOf(
                    "name" to media.name,
                    "bytes" to bytes,
                    "mimeType" to media.mimeType,
                    "usedOriginalUri" to (originalUri != media.uri),
                    "source" to "camera_original_list",
                    "context" to mediaContext(media, "camera_original_list", originalUri != media.uri)
                )
            )
        } catch (error: Exception) {
            completePickError("load_camera_failed", error.message ?: "Could not load the selected camera photo.")
        }
    }

    private fun queryImageById(id: Long): MediaItem? {
        contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            imageProjection(),
            "${MediaStore.Images.Media._ID} = ?",
            arrayOf(id.toString()),
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                return mediaItemFromCursor(cursor)
            }
        }
        return null
    }

    private fun imageProjection(): Array<String> {
        val projection = mutableListOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.MIME_TYPE,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.DATE_ADDED,
            MediaStore.Images.Media.SIZE,
            MediaStore.Images.Media.WIDTH,
            MediaStore.Images.Media.HEIGHT,
            MediaStore.Images.Media.BUCKET_DISPLAY_NAME
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            projection.add(MediaStore.Images.Media.RELATIVE_PATH)
        }
        return projection.toTypedArray()
    }

    private fun cameraImageSelection(): String {
        val selectionParts = mutableListOf("${MediaStore.Images.Media.MIME_TYPE} = ?")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            selectionParts.add("${MediaStore.Images.Media.RELATIVE_PATH} LIKE ?")
        }
        return selectionParts.joinToString(" AND ")
    }

    private fun cameraImageSelectionArgs(): Array<String> {
        val args = mutableListOf("image/jpeg")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            args.add("%DCIM/Camera%")
        }
        return args.toTypedArray()
    }

    private fun mediaItemFromCursor(cursor: android.database.Cursor): MediaItem {
        val id = cursor.getLong(cursor.getColumnIndexOrThrow(MediaStore.Images.Media._ID))
        val name = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME))
            ?: "camera_original.jpg"
        val mimeType = cursor.getString(cursor.getColumnIndexOrThrow(MediaStore.Images.Media.MIME_TYPE))
            ?: "image/jpeg"
        val uri = ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id)
        return MediaItem(
            id = id,
            uri = uri,
            name = name,
            mimeType = mimeType,
            dateTaken = cursorLong(cursor, MediaStore.Images.Media.DATE_TAKEN),
            dateAdded = cursorLong(cursor, MediaStore.Images.Media.DATE_ADDED),
            sizeBytes = cursorLong(cursor, MediaStore.Images.Media.SIZE),
            width = cursorInt(cursor, MediaStore.Images.Media.WIDTH),
            height = cursorInt(cursor, MediaStore.Images.Media.HEIGHT),
            relativePath = cursorString(cursor, MediaStore.Images.Media.RELATIVE_PATH),
            bucketName = cursorString(cursor, MediaStore.Images.Media.BUCKET_DISPLAY_NAME)
        )
    }

    private fun thumbnailBytes(uri: Uri): ByteArray? {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return null
        }
        return try {
            val bitmap = contentResolver.loadThumbnail(uri, Size(240, 240), null)
            ByteArrayOutputStream().use { output ->
                bitmap.compress(Bitmap.CompressFormat.JPEG, 72, output)
                output.toByteArray()
            }
        } catch (_: Exception) {
            null
        }
    }

    private fun cursorLong(cursor: android.database.Cursor, column: String): Long {
        val index = cursor.getColumnIndex(column)
        return if (index >= 0 && !cursor.isNull(index)) cursor.getLong(index) else 0L
    }

    private fun cursorInt(cursor: android.database.Cursor, column: String): Int {
        val index = cursor.getColumnIndex(column)
        return if (index >= 0 && !cursor.isNull(index)) cursor.getInt(index) else 0
    }

    private fun cursorString(cursor: android.database.Cursor, column: String): String {
        val index = cursor.getColumnIndex(column)
        return if (index >= 0 && !cursor.isNull(index)) cursor.getString(index) ?: "" else ""
    }

    private fun mediaContext(media: MediaItem, source: String, usedOriginalUri: Boolean): Map<String, Any?> {
        return mapOf(
            "source" to source,
            "usedOriginalUri" to usedOriginalUri,
            "filename" to media.name,
            "mimeType" to media.mimeType,
            "mediaStoreId" to media.id,
            "dateTaken" to media.dateTaken,
            "dateAdded" to media.dateAdded,
            "sizeBytes" to media.sizeBytes,
            "width" to media.width,
            "height" to media.height,
            "relativePath" to media.relativePath,
            "bucketName" to media.bucketName,
            "uriAuthority" to media.uri.authority
        )
    }

    private fun selectedUriContext(
        uri: Uri,
        name: String,
        mimeType: String,
        usedOriginalUri: Boolean
    ): Map<String, Any?> {
        val context = mutableMapOf<String, Any?>(
            "source" to "selected_image",
            "usedOriginalUri" to usedOriginalUri,
            "filename" to name,
            "mimeType" to mimeType,
            "uriAuthority" to uri.authority
        )
        contentResolver.query(
            uri,
            arrayOf(OpenableColumns.SIZE, OpenableColumns.DISPLAY_NAME),
            null,
            null,
            null
        )?.use { cursor ->
            if (cursor.moveToFirst()) {
                val sizeIndex = cursor.getColumnIndex(OpenableColumns.SIZE)
                if (sizeIndex >= 0 && !cursor.isNull(sizeIndex)) {
                    context["sizeBytes"] = cursor.getLong(sizeIndex)
                }
                val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
                if (nameIndex >= 0 && !cursor.isNull(nameIndex)) {
                    context["displayName"] = cursor.getString(nameIndex)
                }
            }
        }
        return context
    }

    private fun isSupportedImageFile(name: String, mimeType: String): Boolean {
        val normalizedMime = mimeType.trim().lowercase()
        if (normalizedMime.startsWith("image/")) {
            return true
        }
        val normalizedName = name.trim().lowercase()
        return normalizedName.endsWith(".jpg") ||
            normalizedName.endsWith(".jpeg") ||
            normalizedName.endsWith(".png") ||
            normalizedName.endsWith(".webp") ||
            normalizedName.endsWith(".bmp") ||
            normalizedName.endsWith(".tif") ||
            normalizedName.endsWith(".tiff")
    }

    private fun queryCameraTwinForExportedName(displayName: String): MediaItem? {
        val match = androidExportedNamePattern.matchEntire(displayName) ?: return null
        val datePart = match.groupValues[1]
        val timePart = match.groupValues[2]
        val cameraNameFragment = "${datePart}_${timePart}"
        return queryCameraImageByNameFragment(cameraNameFragment)
    }

    private fun queryCameraImageByNameFragment(fragment: String): MediaItem? {
        val selectionParts = mutableListOf(
            "${MediaStore.Images.Media.MIME_TYPE} = ?",
            "${MediaStore.Images.Media.DISPLAY_NAME} LIKE ?"
        )
        val selectionArgs = mutableListOf("image/jpeg", "%$fragment%")
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            selectionParts.add("${MediaStore.Images.Media.RELATIVE_PATH} LIKE ?")
            selectionArgs.add("%DCIM/Camera%")
        }

        val sortOrder =
            "${MediaStore.Images.Media.DATE_TAKEN} DESC, ${MediaStore.Images.Media.DATE_ADDED} DESC"
        contentResolver.query(
            MediaStore.Images.Media.EXTERNAL_CONTENT_URI,
            imageProjection(),
            selectionParts.joinToString(" AND "),
            selectionArgs.toTypedArray(),
            sortOrder
        )?.use { cursor ->
            if (!cursor.moveToFirst()) {
                return null
            }
            return mediaItemFromCursor(cursor)
        }
        return null
    }

    private fun originalMediaUri(uri: Uri): Uri {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.Q) {
            return uri
        }
        return try {
            MediaStore.setRequireOriginal(uri)
        } catch (_: SecurityException) {
            uri
        } catch (_: IllegalArgumentException) {
            uri
        }
    }

    private fun readUriBytes(uri: Uri): ByteArray? {
        return contentResolver.openInputStream(uri)?.use { input -> input.readBytes() }
    }

    private fun displayName(uri: Uri): String {
        contentResolver.query(uri, arrayOf(OpenableColumns.DISPLAY_NAME), null, null, null)?.use { cursor ->
            val nameIndex = cursor.getColumnIndex(OpenableColumns.DISPLAY_NAME)
            if (nameIndex >= 0 && cursor.moveToFirst()) {
                val name = cursor.getString(nameIndex)
                if (!name.isNullOrBlank()) {
                    return name
                }
            }
        }

        val mimeType = contentResolver.getType(uri)
        val extension = MimeTypeMap.getSingleton().getExtensionFromMimeType(mimeType) ?: "jpg"
        return "original_image.$extension"
    }

    private fun completePick(value: Any?) {
        pendingPickResult?.success(value)
        pendingPickResult = null
    }

    private fun completePickError(code: String, message: String) {
        pendingPickResult?.error(code, message, null)
        pendingPickResult = null
    }
}
