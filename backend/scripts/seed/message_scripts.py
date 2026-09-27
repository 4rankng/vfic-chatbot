"""Pre-built chat scripts for the seeded conversations.

Each entry is a full thread as an ordered list of ``(sender, body)`` tuples.
``CONVERSATION_SCRIPTS`` are bot-handled threads; ``RECRUITER_SCRIPTS`` are the
recruiter takeover threads. The builder in :mod:`scripts.seed.messages` cycles
them per conversation, so a thread's length and tone stay stable across seeds.
"""

from __future__ import annotations

from app.models.conversation import MessageSender

CONVERSATION_SCRIPTS: list[list[tuple[MessageSender, str]]] = [
    # --- Script 0: New candidate exploring LG Hải Phòng (long, ~20 messages) ---
    [
        (MessageSender.WORKER, "Xin chào, mình muốn hỏi về việc tuyển công nhân bên mình ạ"),
        (
            MessageSender.BOT,
            "Dạ chào bạn 👋 Mình là trợ lý tuyển dụng của VFIC. Bạn muốn tìm hiểu về công việc nào ạ?",
        ),
        (
            MessageSender.WORKER,
            "Mình nghe nói bên LG Display đang tuyển công nhân sản xuất, đúng không ạ?",
        ),
        (
            MessageSender.BOT,
            "Dạ đúng rồi ạ! LG Display Hải Phòng đang tuyển công nhân sản xuất màn hình LCD/LED. Bạn quan tâm đúng không ạ?",
        ),
        (MessageSender.WORKER, "Dạ, cho mình hỏi lương bao nhiêu ạ?"),
        (
            MessageSender.BOT,
            "Dạ mức lương từ 7-12 triệu VNĐ/tháng tùy ca làm việc và vị trí nhé ạ:\n• Ca 3 vòng: 7-9 triệu\n• Ca 4: 9-12 triệu",
        ),
        (
            MessageSender.WORKER,
            "Ồ lương cao quá. Mình ở Thái Bình, bên mình có hỗ trợ chỗ ở không ạ?",
        ),
        (
            MessageSender.BOT,
            "Dạ có hỗ trợ ạ! Nhà máy có ký túc xá cho công nhân ngoại tỉnh, 6 người/phòng, có điều hòa và nước nóng lạnh nhé.",
        ),
        (MessageSender.WORKER, "Tốt quá. Vậy có xe đưa đón từ Thái Bình không ạ?"),
        (
            MessageSender.BOT,
            "Dạ có xe đưa đón miễn phí từ Thái Bình bạn ạ. Xe chạy 5h15, 5h45 và 13h00 hàng ngày. Mình gửi lịch xe chi tiết nhé!",
        ),
        (
            MessageSender.WORKER,
            "Ok em cảm ơn. Mình 28 tuổi, chưa có kinh nghiệm làm việc ở nhà máy trước. Vậy mình làm được không ạ?",
        ),
        (
            MessageSender.BOT,
            "Dạ bạn 28 tuổi hoàn toàn đáp ứng yêu cầu ạ (nhà máy nhận từ 18-45 tuổi). Không cần kinh nghiệm, nhà máy sẽ đào tạo từ đầu, bạn yên tâm nhé!",
        ),
        (MessageSender.WORKER, "Bảo hiểm bên mình đóng như thế nào ạ?"),
        (
            MessageSender.BOT,
            "Dạ nhà máy đóng đầy đủ bảo hiểm theo luật Việt Nam: BHXH, BHYT, BHTN ạ. Ngoài ra còn có thưởng tháng 13 và thưởng KPI hàng quý.",
        ),
        (MessageSender.WORKER, "Thử việc bao lâu ạ?"),
        (
            MessageSender.BOT,
            "Dạ thời gian thử việc 2 tháng, lương bằng 85% lương chính thức. Sau thử việc ký hợp đồng 12 tháng nhé.",
        ),
        (MessageSender.WORKER, "Ca làm việc như thế nào ạ?"),
        (
            MessageSender.BOT,
            "Dạ nhà máy có ca 3 vòng (6h-14h, 14h-22h, 22h-6h) hoặc ca 4 tùy vị trí. Mỗi ca 8 tiếng, được nghỉ 1 ngày/tuần.",
        ),
        (MessageSender.WORKER, "Mình muốn biết thêm về bữa ăn bên nhà máy ạ"),
        (
            MessageSender.BOT,
            "Dạ nhà máy hỗ trợ bữa ăn trưa, 25.000 VNĐ/bữa. Canteen trong khuôn viên nhà máy, có nhiều món để chọn ạ.",
        ),
        (MessageSender.WORKER, "Ok, vậy cho mình hỏi quy trình đăng ký như thế nào ạ?"),
        (
            MessageSender.BOT,
            "Dạ quy trình rất đơn giản:\n1️⃣ Đăng ký qua Zalo (như bạn đang làm)\n2️⃣ Phỏng vấn trực tiếp\n3️⃣ Khám sức khỏe\n4️⃣ Nhận việc trong 3-5 ngày\n\nBạn cho mình xin tên và số điện thoại để tạo hồ sơ nhé!",
        ),
        (MessageSender.WORKER, "Dạ mình tên Nguyễn Văn An, số điện thoại 0371234567 ạ"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn anh An! Mình đã ghi nhận thông tin. Phòng nhân sự sẽ liên hệ anh trong 24h để sắp xếp lịch phỏng vấn nhé. Anh còn muốn hỏi thêm gì không ạ?",
        ),
        (MessageSender.WORKER, "Không có gì thêm, em cảm ơn anh nhé!"),
        (
            MessageSender.BOT,
            "Dạ không có gì ạ! Chúc anh một ngày tốt lành 😊 Mình sẽ thông báo kết quả sớm nhất cho anh nhé!",
        ),
    ],
    # --- Script 1: Candidate asking about Samsung (moderate, ~16 messages) ---
    [
        (MessageSender.WORKER, "Alo, bên mình tuyển công nhân SMT phải không ạ?"),
        (
            MessageSender.BOT,
            "Dạ chào bạn ạ! Samsung Bắc Ninh đang tuyển công nhân SMT. Bạn muốn tìm hiểu thêm không ạ?",
        ),
        (MessageSender.WORKER, "Có, cho mình hỏi lương và phúc lợi bên Samsung ạ"),
        (
            MessageSender.BOT,
            "Dạ Samsung Bắc Ninh:\n💰 Lương: 7-11 triệu + thưởng KPI 500k-1.5tr/tháng\n🏠 Bao ăn ở (ký túc xá 4-6 người/phòng)\n🚌 Xe đưa đón miễn phí từ 8 tỉnh\n🍽️ 3 bữa/ngày\n🛡️ BHXH đầy đủ",
        ),
        (MessageSender.WORKER, "Làm mấy ca ạ?"),
        (
            MessageSender.BOT,
            "Dạ bên Samsung có ca 3 vòng hoặc ca 2 vòng sáng-chiều bạn ạ. Mỗi ca 8 tiếng, được làm thêm giờ nếu muốn.",
        ),
        (MessageSender.WORKER, "Mình ở Hà Nội, xe mấy giờ đón ạ?"),
        (
            MessageSender.BOT,
            "Dạ xe từ Hà Nội chạy 5h00, 5h30, 6h00 hàng ngày. Lễ Tết có xe tăng cường nhé. Bạn chỉ cần ra điểm tập kết gần nhà.",
        ),
        (MessageSender.WORKER, "Có cần kinh nghiệm không ạ?"),
        (
            MessageSender.BOT,
            "Dạ không yêu cầu kinh nghiệm ạ. Nhà máy đào tạo từ đầu. Chỉ cần tuổi 18-45, biết đọc viết, khỏe mạnh là được.",
        ),
        (MessageSender.WORKER, "Thử việc mấy tháng?"),
        (
            MessageSender.BOT,
            "Dạ thử việc 2 tháng, lương 85%. Sau đó ký hợp đồng chính thức 1 năm.",
        ),
        (MessageSender.WORKER, "Được, mình muốn đăng ký. Tên mình Trần Đức Bình, 0351234567"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn anh Bình! Mình đã tạo hồ sơ. Bộ phận tuyển dụng sẽ gọi anh trong 1-2 ngày để hẹn lịch phỏng vấn nhé.",
        ),
        (MessageSender.WORKER, "Vâng ạ, cảm ơn em"),
        (MessageSender.BOT, "Dạ không có gì ạ! Chúc anh gặp nhiều may mắn 😊"),
    ],
    # --- Script 2: Long negotiation-style conversation (~24 messages) ---
    [
        (MessageSender.WORKER, "Cho mình hỏi bên mình đang tuyển gì ạ?"),
        (
            MessageSender.BOT,
            "Dạ chào bạn! VFIC đang tuyển cho nhiều nhà máy. Bạn muốn làm ở tỉnh nào ạ?",
        ),
        (MessageSender.WORKER, "Mình ở Bắc Ninh, gần nhà nên muốn làm ở Bắc Ninh"),
        (
            MessageSender.BOT,
            "Dạ ở Bắc Ninh có LG Display và Samsung. Cả hai đều tuyển công nhân sản xuất ạ.",
        ),
        (MessageSender.WORKER, "Nơi nào lương cao hơn ạ?"),
        (
            MessageSender.BOT,
            "Dạ so sánh nhanh cho bạn nhé:\n• LG Display: 7.5-13 triệu\n• Samsung: 7-11 triệu + thưởng KPI\n\nLG lương cao hơn nhưng Samsung có 3 bữa ăn/ngày. Tùy bạn ưu tiên nào ạ.",
        ),
        (MessageSender.WORKER, "Mình quan tâm LG hơn. Nhưng mình chưa có kinh nghiệm gì hết"),
        (
            MessageSender.BOT,
            "Dạ không sao ạ! LG Display nhận cả người chưa có kinh nghiệm. Bạn bao nhiêu tuổi ạ?",
        ),
        (MessageSender.WORKER, "Mình 22 tuổi ạ"),
        (MessageSender.BOT, "Dạ 22 tuổi hoàn toàn OK ạ (yêu cầu 18-40). Bạn nam hay nữ ạ?"),
        (MessageSender.WORKER, "Nam ạ"),
        (
            MessageSender.BOT,
            "Dạ LG Bắc Ninh ưu tiên nam cho vị trí Assembly. Lương ca 3: 8-10 triệu, ca ngày: 10-13 triệu.",
        ),
        (MessageSender.WORKER, "Cho mình hỏi về chỗ ở ạ"),
        (
            MessageSender.BOT,
            "Dạ LG hỗ trợ 500.000 VNĐ/tháng nhà ở cho người ngoại tỉnh. Bạn ở Bắc Ninh thì gần nhà rồi, nhưng vẫn nhận được hỗ trợ này ạ.",
        ),
        (MessageSender.WORKER, "Vậy bảo hiểm thì sao ạ?"),
        (
            MessageSender.BOT,
            "Dạ đóng đầy đủ BHXH, BHYT, BHTN. Ngoài ra còn có thưởng tháng 13 và thưởng hiệu quả sản xuất.",
        ),
        (MessageSender.WORKER, "Có được làm thêm giờ không ạ? Mình muốn kiếm thêm thu nhập"),
        (
            MessageSender.BOT,
            "Dạ được làm thêm giờ ạ, lương x1.5 ngày thường và x2 ngày lễ. Nhiều công nhân làm thêm được 2-3 triệu/tháng.",
        ),
        (MessageSender.WORKER, "Tốt quá! Mình muốn hỏi thêm về môi trường làm việc ạ"),
        (
            MessageSender.BOT,
            "Dạ LG Display là công ty Hàn Quốc, môi trường làm việc hiện đại, nhà xưởng sạch sẽ, có máy lạnh. Quy trình sản xuất chuẩn ISO.",
        ),
        (MessageSender.WORKER, "Đồng phục có cấp không ạ?"),
        (
            MessageSender.BOT,
            "Dạ có, cấp 2 bộ đồng phục/năm, miễn phí ạ. Ngoài ra còn có bảo hộ lao động đầy đủ.",
        ),
        (MessageSender.WORKER, "Ok, vậy cho mình hỏi quy trình ứng tuyển ạ"),
        (
            MessageSender.BOT,
            "Dạ: 1) Đăng ký qua đây 2) Phỏng vấn 3) Khám sức khỏe 4) Nhận việc 3-5 ngày. Bạn cho mình xin tên và SĐT nhé!",
        ),
        (MessageSender.WORKER, "Dạ Lê Quang Cường, 0381234567"),
        (
            MessageSender.BOT,
            "Dạ ghi nhận anh Cường! Tuyển dụng sẽ gọi anh trong 24h. Anh còn câu hỏi gì không ạ?",
        ),
        (MessageSender.WORKER, "Không ạ, cảm ơn em rất nhiều"),
        (MessageSender.BOT, "Dạ không có gì ạ! Chúc anh một tuần tốt lành 😊"),
    ],
    # --- Script 3: Short casual chat (~12 messages) ---
    [
        (MessageSender.WORKER, "Nhà mình có bao ăn ở không ạ?"),
        (MessageSender.BOT, "Dạ chào bạn! Bạn muốn hỏi về nhà máy nào ạ?"),
        (MessageSender.WORKER, "LG Display Hải Phòng ạ"),
        (
            MessageSender.BOT,
            "Dạ LG Hải Phòng hỗ trợ bao ăn ở: ký túc xá 6 người/phòng, có điều hòa. Bữa ăn trưa 25.000đ/bữa ạ.",
        ),
        (MessageSender.WORKER, "Lương bao nhiêu ạ?"),
        (MessageSender.BOT, "Dạ 7-12 triệu tùy ca. Ca 3: 7-9tr, ca 4: 9-12tr."),
        (MessageSender.WORKER, "Mình muốn đăng ký ạ"),
        (MessageSender.BOT, "Dạ bạn cho mình xin tên và số điện thoại nhé!"),
        (MessageSender.WORKER, "Phạm Hoàng Dũng, 0341234567"),
        (MessageSender.BOT, "Dạ cảm ơn anh Dũng! Tuyển dụng sẽ liên hệ anh sớm ạ."),
        (MessageSender.WORKER, "Cảm ơn em"),
        (MessageSender.BOT, "Dạ không có gì ạ! 😊"),
    ],
    # --- Script 4: Foxconn Nghệ An inquiry (~14 messages) ---
    [
        (MessageSender.WORKER, "Xin hỏi Foxconn Nghệ An có tuyển người không ạ?"),
        (
            MessageSender.BOT,
            "Dạ có ạ! Foxconn Nghệ An đang tuyển công nhân lắp ráp điện tử. Bạn quan tâm đúng không ạ?",
        ),
        (MessageSender.WORKER, "Dạ, cho mình hỏi lương và chỗ ở ạ"),
        (
            MessageSender.BOT,
            "Dạ Foxconn Nghệ An:\n💰 Lương: 6.5-10 triệu\n🏠 Hỗ trợ 400.000đ/tháng nhà ở\n🚌 Xe đưa đón từ Vinh, Hà Tĩnh, Quảng Bình\n🍽️ Ăn trưa 20.000đ/bữa\n🛡️ BHXH đầy đủ",
        ),
        (MessageSender.WORKER, "Mình ở Hà Tĩnh, xe mấy giờ ạ?"),
        (
            MessageSender.BOT,
            "Dạ xe từ Hà Tĩnh 5h30 hàng ngày. Lễ Tết tăng chuyến. Bạn ra bến xe Vinh là có xe đón ạ.",
        ),
        (MessageSender.WORKER, "Có làm thêm giờ không?"),
        (
            MessageSender.BOT,
            "Dạ có, làm thêm nhiều. Lương x1.5 ngày thường, x2 ngày lễ. Nhiều bạn làm thêm được 2-3 triệu/tháng.",
        ),
        (MessageSender.WORKER, "Không cần kinh nghiệm chứ ạ?"),
        (
            MessageSender.BOT,
            "Dạ đúng rồi, không yêu cầu kinh nghiệm. Tuổi 18-45, khỏe mạnh, biết đọc viết là được.",
        ),
        (MessageSender.WORKER, "Thử việc mấy tháng?"),
        (MessageSender.BOT, "Dạ 2 tháng, lương 85%. Sau đó ký HĐ 12 tháng."),
        (MessageSender.WORKER, "Mình đăng ký nhé. Đặng Thanh Em, 0361234567"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn anh Em! Tuyển dụng sẽ gọi anh trong 1-2 ngày nhé. Chúc anh may mắn! 😊",
        ),
        (MessageSender.WORKER, "Cảm ơn em nhé"),
    ],
    # --- Script 5: Detailed QC/KCS role inquiry (~18 messages) ---
    [
        (MessageSender.WORKER, "Xin chào, mình có 2 năm kinh nghiệm QC ở công ty dệt may"),
        (
            MessageSender.BOT,
            "Dạ chào bạn! Kinh nghiệm QC rất quý ạ. Bạn muốn ứng tuyển vị trí nào bên mình?",
        ),
        (MessageSender.WORKER, "Mình muốn làm QC/KCS bên nhà máy điện tử ạ"),
        (
            MessageSender.BOT,
            "Dạ bên mình có tuyển QC/KCS cho LG Display và Samsung. Bạn muốn làm ở tỉnh nào ạ?",
        ),
        (MessageSender.WORKER, "Bắc Ninh, gần nhà mình"),
        (
            MessageSender.BOT,
            "Dạ QC/KCS tại LG Bắc Ninh lương 8.5-14 triệu, ca ngày. Samsung Bắc Ninh cũng tuyển QC lương tương đương.",
        ),
        (MessageSender.WORKER, "Lương 8.5-14 triệu đó từ thấp đến cao là sao ạ?"),
        (
            MessageSender.BOT,
            "Dạ phụ thuộc vào kinh nghiệm và chứng chỉ ạ:\n• 1-2 năm kinh nghiệm: 8.5-10 triệu\n• 3+ năm hoặc có chứng chỉ ISO: 10-14 triệu\n\nMình đã có 2 năm kinh nghiệm QC nên bạn sẽ được xét lương khá tốt nhé.",
        ),
        (MessageSender.WORKER, "Có hỗ trợ ăn ở không ạ?"),
        (
            MessageSender.BOT,
            "Dạ có. LG hỗ trợ 500k/tháng nhà ở, ăn trưa 25k/bữa. Samsung bao ăn ở luôn (ký túc xá + 3 bữa/ngày).",
        ),
        (MessageSender.WORKER, "Xe đưa đón không ạ?"),
        (MessageSender.BOT, "Dạ cả hai đều có xe đưa đón miễn phí từ các tỉnh lân cận ạ."),
        (MessageSender.WORKER, "Có đào tạo thêm không?"),
        (
            MessageSender.BOT,
            "Dạ có. Nhà máy thường xuyên đào tạo nâng cao tay nghề, kỹ năng kiểm soát chất lượng theo chuẩn quốc tế.",
        ),
        (MessageSender.WORKER, "Mình rất thích. Cho mình hỏi thêm về hợp đồng ạ"),
        (
            MessageSender.BOT,
            "Dạ HĐ 12 tháng, thử việc 2 tháng. Sau thử việc có đánh giá năng lực để điều chỉnh lương.",
        ),
        (
            MessageSender.WORKER,
            "Ok mình muốn đăng ký vị trí QC bên Samsung ạ. Vũ Đình Giang, 0331234567",
        ),
        (
            MessageSender.BOT,
            "Dạ ghi nhận anh Giang! Với kinh nghiệm 2 năm QC, hồ sơ của anh sẽ được ưu tiên xem xét. Tuyển dụng gọi anh trong 24h nhé!",
        ),
        (MessageSender.WORKER, "Cảm ơn em nha"),
        (MessageSender.BOT, "Dạ không có gì ạ! Chúc anh ứng tuyển thành công! 😊"),
    ],
    # --- Script 6: Very long multi-topic conversation (~28 messages) ---
    [
        (MessageSender.WORKER, "Chào em, anh muốn hỏi thông tin tuyển dụng ạ"),
        (
            MessageSender.BOT,
            "Dạ chào anh! Em là trợ lý tuyển dụng VFIC. Anh muốn tìm hiểu về vị trí nào ạ?",
        ),
        (MessageSender.WORKER, "Anh muốn làm công nhân sản xuất bên LG"),
        (
            MessageSender.BOT,
            "Dạ LG có hai nhà máy: Hải Phòng và Bắc Ninh. Anh muốn làm ở đâu ạ?",
        ),
        (MessageSender.WORKER, "Hải Phòng đi, ở gần quê anh hơn"),
        (
            MessageSender.BOT,
            "Dạ LG Display Hải Phòng tuyển công nhân sản xuất màn hình LCD/LED. Mức lương 7-12 triệu tùy ca ạ.",
        ),
        (MessageSender.WORKER, "Cho anh hỏi ca làm việc chi tiết hơn ạ"),
        (
            MessageSender.BOT,
            "Dạ có 3 loại ca ạ:\n🌅 Ca sáng: 6h00 - 14h00\n☀️ Ca chiều: 14h00 - 22h00\n🌙 Ca đêm: 22h00 - 6h00 (ca 3)\n\nMỗi ca 8 tiếng, nghỉ 1 ngày/tuần luân phiên.",
        ),
        (MessageSender.WORKER, "Ca đêm có phụ cấp không ạ?"),
        (
            MessageSender.BOT,
            "Dạ ca đêm có phụ cấp thêm khoảng 20-30% so với ca ngày. Nhiều bạn thích ca đêm vì lương cao hơn.",
        ),
        (MessageSender.WORKER, "Nếu anh chọn ca sáng thì lương bao nhiêu?"),
        (
            MessageSender.BOT,
            "Dạ ca sáng khoảng 7-8 triệu + thưởng KPI. Nếu làm thêm giờ thì tổng thu nhập 9-11 triệu/tháng.",
        ),
        (MessageSender.WORKER, "Anh ở Hải Phòng luôn, vậy không cần chỗ ở đúng không?"),
        (
            MessageSender.BOT,
            "Dạ anh ở Hải Phòng thì không cần ký túc xá. Nhưng nếu ở xa nhà máy thì vẫn có xe đưa đón ạ.",
        ),
        (MessageSender.WORKER, "Từ trung tâm Hải Phòng đến nhà máy bao xa ạ?"),
        (
            MessageSender.BOT,
            "Dạ nhà máy ở KCN Tràng Duệ, cách trung tâm thành phố khoảng 20km. Xe chạy khoảng 30-40 phút ạ.",
        ),
        (MessageSender.WORKER, "Ok, vậy bảo hiểm thế nào ạ?"),
        (
            MessageSender.BOT,
            "Dạ BHXH, BHYT, BHTN đóng đầy đủ. Ngoài ra công ty còn có quỹ hưu trí tự nguyện và bảo hiểm tai nạn ạ.",
        ),
        (MessageSender.WORKER, "Thưởng hàng năm thế nào ạ?"),
        (
            MessageSender.BOT,
            "Dạ có thưởng tháng 13 (1 tháng lương), thưởng KPI hàng quý, và thưởng chuyên cần ạ.",
        ),
        (
            MessageSender.WORKER,
            "Kỹ thuật bảo trì thì lương bao nhiêu ạ? Anh cũng biết sửa máy móc",
        ),
        (
            MessageSender.BOT,
            "Dạ vị trí kỹ thuật bảo trì lương 10-18 triệu. Nhưng yêu cầu 2 năm kinh nghiệm. Anh có kinh nghiệm sửa máy điện tử không ạ?",
        ),
        (MessageSender.WORKER, "Anh biết sửa máy may công nghiệp, chưa sửa máy điện tử"),
        (
            MessageSender.BOT,
            "Dạ thì anh đăng ký công nhân sản xuất trước nhé. Khi vào làm, nếu học nhanh thì有机会 thăng lên vị trí kỹ thuật sau 6-12 tháng.",
        ),
        (MessageSender.WORKER, "Ý hay đấy! Vậy quy trình đăng ký thế nào ạ?"),
        (
            MessageSender.BOT,
            "Dạ rất đơn giản:\n1️⃣ Anh cho em xin tên và SĐT\n2️⃣ Tuyển dụng gọi hẹn phỏng vấn\n3️⃣ Phỏng vấn + khám sức khỏe\n4️⃣ Nhận việc trong 3-5 ngày",
        ),
        (MessageSender.WORKER, "Bùi Xuân Hải, 0391234567"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn anh Hải! Mình đã tạo hồ sơ. Bộ phận tuyển dụng sẽ gọi anh trong 24h. Anh còn gì thắc mắc không ạ?",
        ),
        (MessageSender.WORKER, "Không có gì nữa, em nhiệt tình ghê 😄"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn anh ạ! Chúc anh một ngày tốt lành! Hẹn gặp anh tại LG Display nhé! 😊",
        ),
    ],
    # --- Script 7: Candidate with tattoos concern (~14 messages) ---
    [
        (MessageSender.WORKER, "Xin hỏi bên mình có nhận người xăm hình không ạ?"),
        (MessageSender.BOT, "Dạ chào bạn! Bạn đang quan tâm vị trí nào ạ?"),
        (MessageSender.WORKER, "Công nhân sản xuất bên LG ạ"),
        (
            MessageSender.BOT,
            "Dạ LG Display có thể nhận bạn xăm hình tùy vị trí và khu vực xăm ạ. Bạn xăm ở đâu, xăm hình gì mình hỏi để tư vấn chính xác hơn nhé.",
        ),
        (MessageSender.WORKER, "Mình xăm ở cánh tay và ngực ạ"),
        (
            MessageSender.BOT,
            "Dạ xăm cánh tay có thể được chấp nhận nếu nhỏ và không quá lộ. Xăm ngực thì không vấn đề vì mặc đồng phục sẽ che. Tuy nhiên khi phỏng vấn cần khai báo thật để bên nhân sự đánh giá nhé.",
        ),
        (MessageSender.WORKER, "Vậy mình vẫn có thể đăng ký được đúng không ạ?"),
        (
            MessageSender.BOT,
            "Dạ được ạ! Mình khuyến khích bạn đăng ký và khai báo thật trong buổi phỏng vấn. Có một số bạn xăm hình nhỏ vẫn được nhận ạ.",
        ),
        (MessageSender.WORKER, "Ok, vậy lương bên LG bao nhiêu ạ?"),
        (MessageSender.BOT, "Dạ 7-12 triệu tùy ca. Có hỗ trợ ăn ở và xe đưa đón ạ."),
        (MessageSender.WORKER, "Mình muốn đăng ký. Đỗ Anh Khôi, 0311234567"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn anh Khôi! Tuyển dụng sẽ gọi anh trong 24h. Nhớ khai báo xăm hình khi phỏng vấn nhé ạ.",
        ),
        (MessageSender.WORKER, "Vâng em ạ"),
        (MessageSender.BOT, "Dạ chúc anh may mắn! 😊"),
    ],
    # --- Script 8: Short inquiry about bus timetable (~10 messages) ---
    [
        (MessageSender.WORKER, "Xin hỏi xe bus từ Hải Phòng mấy giờ chạy ạ?"),
        (
            MessageSender.BOT,
            "Dạ xe đưa đón công nhân LG Display Hải Phòng:\n🚌 Tuyến Hải Phòng: 5h15, 5h45, 13h00\n\nBạn ở khu vực nào để mình tư vấn điểm lên xe gần nhất ạ?",
        ),
        (MessageSender.WORKER, "Mình ở quận Ngô Quyền ạ"),
        (
            MessageSender.BOT,
            "Dạ điểm tập kết gần Ngô Quyền là bến xe Niệm Nghĩa. Xe đến khoảng 5h10-5h20 ạ.",
        ),
        (MessageSender.WORKER, "Có xe về chiều không ạ?"),
        (
            MessageSender.BOT,
            "Dạ có, xe về chiều chạy 14h00, 22h00 từ nhà máy về bến xe Niệm Nghĩa ạ.",
        ),
        (MessageSender.WORKER, "Cảm ơn em nhé"),
        (MessageSender.BOT, "Dạ không có gì ạ! Nếu cần thông tin khác cứ hỏi nhé 😊"),
    ],
    # --- Script 9: Female candidate asking about gender requirements (~16 messages) ---
    [
        (MessageSender.WORKER, "Chào em, bên mình có nhận nữ công nhân không ạ?"),
        (
            MessageSender.BOT,
            "Dạ chào chị! Có ạ, hầu hết vị trí đều nhận cả nam và nữ. Chị muốn tìm hiểu về vị trí nào ạ?",
        ),
        (MessageSender.WORKER, "Mình muốn làm đóng gói bên Samsung ạ"),
        (
            MessageSender.BOT,
            "Dạ Samsung Bắc Ninh đang tuyển công nhân đóng gói, ưu tiên nữ. Lương 6.5-9 triệu, ca 2 vòng sáng-chiều ạ.",
        ),
        (MessageSender.WORKER, "Ca 2 vòng là mấy giờ ạ?"),
        (
            MessageSender.BOT,
            "Dạ ca sáng: 6h-14h, ca chiều: 14h-22h. Ca 2 vòng thường được nữ công nhân ưa thích vì không phải làm đêm ạ.",
        ),
        (MessageSender.WORKER, "Mình có con nhỏ 2 tuổi, có được làm ca sáng không ạ?"),
        (
            MessageSender.BOT,
            "Dạ được ạ, chị có thể chọn ca sáng 6h-14h. Buổi chiều về còn thời gian lo cho bé ạ.",
        ),
        (MessageSender.WORKER, "Có chỗ ở cho người có gia đình không ạ?"),
        (
            MessageSender.BOT,
            "Dạ Samsung có ký túc xá 4-6 người/phòng. Nếu chị muốn thuê phòng riêng ngoài thì hỗ trợ 500k/tháng ạ.",
        ),
        (MessageSender.WORKER, "Bảo hiểm cho cả con không ạ?"),
        (
            MessageSender.BOT,
            "Dạ bảo hiểm đóng cho người lao động. Con dưới 6 tuổi thì được tham gia BHYT miễn phí cùng mẹ ạ.",
        ),
        (MessageSender.WORKER, "Tốt quá! Mình đăng ký nhé. Nguyễn Thị Oanh, 0321234567"),
        (
            MessageSender.BOT,
            "Dạ cảm ơn chị Oanh! Tuyển dụng sẽ gọi chị trong 24h. Chúc chị một ngày vui vẻ! 😊",
        ),
        (MessageSender.WORKER, "Cảm ơn em"),
        (MessageSender.BOT, "Dạ không có gì ạ!"),
    ],
]

RECRUITER_SCRIPTS: list[list[tuple[MessageSender, str]]] = [
    [
        (
            MessageSender.RECRUITER,
            "Chào anh, em là Lan - tuyển dụng VFIC. Em xem hồ sơ của anh rồi ạ.",
        ),
        (MessageSender.WORKER, "Dạ vâng, em cho anh biết kết quả thế nào ạ"),
        (
            MessageSender.RECRUITER,
            "Anh đáp ứng yêu cầu rồi ạ. Em gửi anh thông tin nhà máy và lịch phỏng vấn nhé.",
        ),
        (MessageSender.WORKER, "Dạ ok em, anh nhận được ạ"),
        (
            MessageSender.RECRUITER,
            "Dạ. Buổi phỏng vấn dự kiến thứ 3 tuần sau, 9h sáng tại nhà máy nhé.",
        ),
        (MessageSender.WORKER, "Vâng, anh sẽ đến đúng giờ ạ"),
        (
            MessageSender.RECRUITER,
            "Anh nhớ mang theo CCCD và hồ sơ nhé. Có gì thắc mắc thì nhắn em ạ.",
        ),
        (MessageSender.WORKER, "Dạ em cảm ơn anh/nhạ"),
        (MessageSender.RECRUITER, "Dạ không có gì ạ! Hẹn gặp anh thứ 3 👋"),
        (MessageSender.WORKER, "Ok anh/chị nha"),
    ],
    [
        (MessageSender.RECRUITER, "Chào chị, em là Minh từ VFIC. Em hỗ trợ chị ạ."),
        (MessageSender.WORKER, "Dạ, em muốn hỏi về hợp đồng lao động ạ"),
        (
            MessageSender.RECRUITER,
            "HĐ 12 tháng, thử việc 2 tháng = 85% lương. Sau thử việc có đánh giá lại lương nhé.",
        ),
        (MessageSender.WORKER, "Dạ hiểu rồi, còn gì không chị cần chuẩn bị ạ?"),
        (
            MessageSender.RECRUITER,
            "Chị cần chuẩn bị: CCCD gốc, sơ yếu lý lịch, và 2 ảnh 3x4 nhé.",
        ),
        (MessageSender.WORKER, "Dạ ok, chị sẽ chuẩn bị ạ"),
        (
            MessageSender.RECRUITER,
            "Dạ hẹn gặp chị tại nhà máy vào thứ 5 tới nhé. Em nhắc lại trước 1 ngày ạ.",
        ),
        (MessageSender.WORKER, "Ok cảm ơn em"),
    ],
]
