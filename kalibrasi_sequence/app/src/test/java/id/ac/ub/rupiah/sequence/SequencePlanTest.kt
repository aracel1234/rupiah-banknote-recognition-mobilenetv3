package id.ac.ub.rupiah.sequence

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class SequencePlanTest {
    @Test
    fun planHasExactThesisComposition() {
        val items = SequencePlan.build()
        assertEquals(40, items.size)
        assertEquals(28, items.count { it.kind == SequenceKind.NOMINAL })
        assertEquals(6, items.count { it.kind == SequenceKind.NONUANG })
        assertEquals(6, items.count { it.kind == SequenceKind.TRANSITION })
        assertEquals(40, items.map { it.id }.toSet().size)
        assertTrue(items.all { it.totalDurationMs == 12_000L })
    }

    @Test
    fun nominalPlanCoversAllSevenNominalsAndFourScenarios() {
        val nominal = SequencePlan.build().filter { it.kind == SequenceKind.NOMINAL }
        SequencePlan.nominalLabels.forEach { label ->
            val subset = nominal.filter { it.primaryLabel == label }
            assertEquals(4, subset.size)
            assertEquals(setOf("stable", "motion", "distance", "orientation"), subset.map { it.scenario }.toSet())
        }
    }
}
