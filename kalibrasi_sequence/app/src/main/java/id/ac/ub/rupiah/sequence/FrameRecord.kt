package id.ac.ub.rupiah.sequence

data class FrameRecord(
    val frameIndex: Int,
    val elapsedMs: Long,
    val stageId: String,
    val stageTitle: String,
    val expectedLabel: String?,
    val analysisRole: String,
    val imageTimestampNs: Long,
    val rotationDegrees: Int,
    val roiWidth: Int,
    val roiHeight: Int,
    val originalMeanY: Double,
    val processedMeanY: Double,
    val laplacianVariance: Double,
    val claheApplied: Boolean,
    val qualityPass: Boolean,
    val qualityCode: String?,
    val scores: FloatArray?,
    val topLabel: String?,
    val topScore: Float?,
    val preprocessMs: Double,
    val inferenceMs: Double,
    val pipelineMs: Double
)

data class SequenceRunStats(
    val cameraFramesSeen: Int,
    val sampledFrames: Int,
    val qualityPassedFrames: Int,
    val qualityRejectedFrames: Int,
    val durationMs: Long,
    val targetFps: Int,
    val medianPipelineMs: Double,
    val p95PipelineMs: Double,
    val achievedSampleFps: Double
)
