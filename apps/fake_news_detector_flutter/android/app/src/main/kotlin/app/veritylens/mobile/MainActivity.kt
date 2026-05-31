package app.veritylens.mobile

import android.Manifest
import android.app.Activity
import android.content.ActivityNotFoundException
import android.content.ContentUris
import android.content.Intent
import android.content.pm.PackageManager
import android.net.Uri
import android.os.Build
import android.provider.MediaStore
import android.provider.OpenableColumns
import android.webkit.MimeTypeMap
import io.flutter.embedding.android.FlutterActivity
import io.flutter.embedding.engine.FlutterEngine
import io.flutter.plugin.common.MethodChannel

class MainActivity : FlutterActivity() {
    private val channelName = "app.veritylens.mobile/original_image_picker"
    private val pickOriginalImageRequest = 4201
    private val permissionRequest = 4202

    private enum class PendingAction {
        PICK_IMAGE,
        LATEST_CAMERA
    }

    private var pendingPickResult: MethodChannel.Result? = null
    private var pendingAction: PendingAction? = null

    override fun configureFlutterEngine(flutterEngine: FlutterEngine) {
        super.configureFlutterEngine(flutterEngine)
        MethodChannel(flutterEngine.dartExecutor.binaryMessenger, channelName).setMethodCallHandler { call, result ->
            when (call.method) {
                "pickOriginalImage" -> pickOriginalImage(result)
                "pickLatestCameraImage" -> pickLatestCameraImage(result)
                else -> result.notImplemented()
            }
        }
    }

    private fun pickOriginalImage(result: MethodChannel.Result) {
        if (!startPending(result)) {
            return
        }
        val permissions = missingPermissions(needsImageReadPermission = false)
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
        val intent = Intent(Intent.ACTION_OPEN_DOCUMENT).apply {
            addCategory(Intent.CATEGORY_OPENABLE)
            type = "image/*"
            putExtra(
                Intent.EXTRA_MIME_TYPES,
                arrayOf("image/jpeg", "image/png", "image/webp", "image/bmp", "image/tiff")
            )
            addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            addFlags(Intent.FLAG_GRANT_PERSISTABLE_URI_PERMISSION)
        }

        try {
            startActivityForResult(intent, pickOriginalImageRequest)
        } catch (_: ActivityNotFoundException) {
            val fallback = Intent(Intent.ACTION_GET_CONTENT).apply {
                addCategory(Intent.CATEGORY_OPENABLE)
                type = "image/*"
                addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            }
            startActivityForResult(fallback, pickOriginalImageRequest)
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

            val originalUri = originalMediaUri(uri)
            val bytes = readUriBytes(originalUri) ?: readUriBytes(uri)
            if (bytes == null) {
                completePickError("read_failed", "Could not read the selected image.")
                return
            }

            completePick(
                mapOf(
                    "name" to displayName(uri),
                    "bytes" to bytes,
                    "mimeType" to (contentResolver.getType(uri) ?: ""),
                    "usedOriginalUri" to (originalUri != uri)
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
                    "source" to "latest_camera"
                )
            )
        } catch (error: Exception) {
            completePickError("latest_camera_failed", error.message ?: "Could not load the latest camera photo.")
        }
    }

    private data class MediaItem(val uri: Uri, val name: String, val mimeType: String)

    private fun queryLatestImage(cameraOnly: Boolean): MediaItem? {
        val projection = mutableListOf(
            MediaStore.Images.Media._ID,
            MediaStore.Images.Media.DISPLAY_NAME,
            MediaStore.Images.Media.MIME_TYPE,
            MediaStore.Images.Media.DATE_TAKEN,
            MediaStore.Images.Media.DATE_ADDED
        )
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            projection.add(MediaStore.Images.Media.RELATIVE_PATH)
        }

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
            projection.toTypedArray(),
            selectionParts.joinToString(" AND "),
            selectionArgs.toTypedArray(),
            sortOrder
        )?.use { cursor ->
            if (!cursor.moveToFirst()) {
                return null
            }
            val idIndex = cursor.getColumnIndexOrThrow(MediaStore.Images.Media._ID)
            val nameIndex = cursor.getColumnIndexOrThrow(MediaStore.Images.Media.DISPLAY_NAME)
            val mimeIndex = cursor.getColumnIndexOrThrow(MediaStore.Images.Media.MIME_TYPE)
            val id = cursor.getLong(idIndex)
            val name = cursor.getString(nameIndex) ?: "camera_original.jpg"
            val mimeType = cursor.getString(mimeIndex) ?: "image/jpeg"
            val uri = ContentUris.withAppendedId(MediaStore.Images.Media.EXTERNAL_CONTENT_URI, id)
            return MediaItem(uri, name, mimeType)
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
