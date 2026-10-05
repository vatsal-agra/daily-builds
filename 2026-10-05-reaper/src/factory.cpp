#include "collectors.hpp"

namespace reaper {

std::vector<std::string> heapKinds() {
  return {"marksweep", "markcompact", "copying", "generational", "incremental"};
}

std::unique_ptr<Heap> makeHeap(const std::string& kind, size_t words, size_t param) {
  if (words < 256) throw std::invalid_argument("heap must be at least 256 words");
  if (kind == "nogc") return std::make_unique<NoGcHeap>(words);
  if (kind == "marksweep") return std::make_unique<MarkSweepHeap>(words);
  if (kind == "markcompact") return std::make_unique<MarkCompactHeap>(words);
  if (kind == "copying") return std::make_unique<CopyingHeap>(words);
  if (kind == "generational") return std::make_unique<GenerationalHeap>(words, param);
  if (kind == "incremental") return std::make_unique<IncrementalHeap>(words, param);
  throw std::invalid_argument("unknown collector '" + kind + "' (try: marksweep markcompact copying generational incremental nogc)");
}

}  // namespace reaper
