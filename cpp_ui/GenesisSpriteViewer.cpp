#include "GenesisSpriteViewer.h"

#include <QPainter>
#include <QVBoxLayout>
#include <QHBoxLayout>
#include <QGridLayout>
#include <QFileDialog>
#include <QJsonDocument>
#include <QJsonObject>
#include <QJsonArray>

#include <iostream>

// ---------------------------------------------------------------------------
// Tile decoder helpers
// ---------------------------------------------------------------------------

static const int TILE_W = 8;
static const int TILE_H = 8;
static const int BYTES_PER_TILE = 32;

QColor decodeCramColor(uint16_t cramWord)
{
    int r = ((cramWord >> 1) & 0x07) * 36;
    int g = ((cramWord >> 5) & 0x07) * 36;
    int b = ((cramWord >> 9) & 0x07) * 36;
    return QColor(r, g, b);
}

QVector<QColor> decodeCramPalette(const QByteArray & paletteBytes)
{
    QVector<QColor> colors;
    if (paletteBytes.size() < 32)
        return grayscalePalette();

    for (int i = 0; i < 16; ++i)
    {
        uint8_t hi = (uint8_t)paletteBytes[i * 2];
        uint8_t lo = (uint8_t)paletteBytes[i * 2 + 1];
        uint16_t word = (hi << 8) | lo;
        colors.append(decodeCramColor(word));
    }
    return colors;
}

QImage decodeTile(const QByteArray & tileBytes, const QVector<QColor> & palette)
{
    QImage img(TILE_W, TILE_H, QImage::Format_ARGB32);
    img.fill(Qt::transparent);

    if (tileBytes.size() < BYTES_PER_TILE || palette.size() < 16)
        return img;

    for (int row = 0; row < TILE_H; ++row)
    {
        int rowOff = row * 4;
        for (int pair = 0; pair < 4; ++pair)
        {
            uint8_t byte = (uint8_t)tileBytes[rowOff + pair];
            int leftIdx  = (byte >> 4) & 0x0F;
            int rightIdx = byte & 0x0F;
            int x = pair * 2;

            img.setPixelColor(x,     row, palette[leftIdx]);
            img.setPixelColor(x + 1, row, palette[rightIdx]);
        }
    }
    return img;
}

QPixmap renderSpriteGrid(const QByteArray & tileData, int widthTiles,
                          int heightTiles, const QVector<QColor> & palette,
                          int zoom)
{
    int totalTiles = widthTiles * heightTiles;
    int neededBytes = totalTiles * BYTES_PER_TILE;

    if (tileData.size() < neededBytes)
        return QPixmap();

    int pixW = widthTiles * TILE_W * zoom;
    int pixH = heightTiles * TILE_H * zoom;

    QPixmap result(pixW, pixH);
    result.fill(QColor(32, 32, 32));

    QPainter painter(&result);
    painter.setRenderHint(QPainter::SmoothPixmapTransform, false);

    for (int col = 0; col < widthTiles; ++col)
    {
        for (int row = 0; row < heightTiles; ++row)
        {
            // Column-major: tile(col, row) = col * H + row
            int tileIdx = col * heightTiles + row;
            int tileOff = tileIdx * BYTES_PER_TILE;
            QByteArray tb = tileData.mid(tileOff, BYTES_PER_TILE);

            QImage tile = decodeTile(tb, palette);

            int dx = col * TILE_W * zoom;
            int dy = row * TILE_H * zoom;
            QRect dest(dx, dy, TILE_W * zoom, TILE_H * zoom);
            painter.drawImage(dest, tile);
        }
    }

    painter.end();
    return result;
}

QVector<QColor> grayscalePalette()
{
    QVector<QColor> pal;
    for (int i = 0; i < 16; ++i)
    {
        int v = i * 17;
        pal.append(QColor(v, v, v));
    }
    return pal;
}


// ---------------------------------------------------------------------------
// Palette swatch widget
// ---------------------------------------------------------------------------

PaletteSwatchWidget::PaletteSwatchWidget(QWidget *parent)
    : QWidget(parent)
    , thePalette(grayscalePalette())
{
    setFixedHeight(SWATCH_SIZE + 4);
    setMinimumWidth(SWATCH_SIZE * 16 + 2);
}

void PaletteSwatchWidget::setPalette(const QVector<QColor> & palette)
{
    thePalette = palette;
    update();
}

void PaletteSwatchWidget::paintEvent(QPaintEvent *)
{
    QPainter p(this);
    for (int i = 0; i < 16 && i < thePalette.size(); ++i)
    {
        p.fillRect(i * SWATCH_SIZE + 1, 2, SWATCH_SIZE - 1, SWATCH_SIZE,
                    thePalette[i]);
    }
    p.setPen(QColor(100, 100, 100));
    p.drawRect(0, 1, 16 * SWATCH_SIZE + 1, SWATCH_SIZE + 1);
}


// ---------------------------------------------------------------------------
// Sprite viewer sidebar widget
// ---------------------------------------------------------------------------

GenesisSpriteViewerWidget::GenesisSpriteViewerWidget(
    const QString & title, ViewFrame *frame, BinaryViewRef data)
    : SidebarWidget(title)
    , theData(data)
    , theFrame(frame)
    , theCurrentOffset(0)
    , theGridW(2)
    , theGridH(4)
    , theZoom(4)
    , theActivePalette(grayscalePalette())
{
    buildUi();

    if (data)
        refreshDisplay();
}

void GenesisSpriteViewerWidget::buildUi()
{
    QVBoxLayout *layout = new QVBoxLayout();
    layout->setContentsMargins(4, 4, 4, 4);
    layout->setSpacing(4);

    // Address display
    QHBoxLayout *addrRow = new QHBoxLayout();
    addrRow->addWidget(new QLabel("Address:"));
    theAddrLabel = new QLabel("0x00000000");
    theAddrLabel->setStyleSheet("font-family: monospace; font-weight: bold;");
    addrRow->addWidget(theAddrLabel);
    addrRow->addStretch();
    layout->addLayout(addrRow);

    // Grid dimensions
    QGroupBox *gridGroup = new QGroupBox("Sprite Grid");
    QGridLayout *gridLayout = new QGridLayout();
    gridLayout->setContentsMargins(4, 4, 4, 4);

    gridLayout->addWidget(new QLabel("Width (tiles):"), 0, 0);
    theWidthSpin = new QSpinBox();
    theWidthSpin->setRange(1, 32);
    theWidthSpin->setValue(theGridW);
    connect(theWidthSpin, SIGNAL(valueChanged(int)), this, SLOT(onGridChanged(int)));
    gridLayout->addWidget(theWidthSpin, 0, 1);

    gridLayout->addWidget(new QLabel("Height (tiles):"), 1, 0);
    theHeightSpin = new QSpinBox();
    theHeightSpin->setRange(1, 32);
    theHeightSpin->setValue(theGridH);
    connect(theHeightSpin, SIGNAL(valueChanged(int)), this, SLOT(onGridChanged(int)));
    gridLayout->addWidget(theHeightSpin, 1, 1);

    gridLayout->addWidget(new QLabel("Zoom:"), 2, 0);
    theZoomSpin = new QSpinBox();
    theZoomSpin->setRange(1, 16);
    theZoomSpin->setValue(theZoom);
    connect(theZoomSpin, SIGNAL(valueChanged(int)), this, SLOT(onZoomChanged(int)));
    gridLayout->addWidget(theZoomSpin, 2, 1);

    gridGroup->setLayout(gridLayout);
    layout->addWidget(gridGroup);

    // Palette controls
    QGroupBox *palGroup = new QGroupBox("Palette");
    QVBoxLayout *palLayout = new QVBoxLayout();
    palLayout->setContentsMargins(4, 4, 4, 4);

    QHBoxLayout *palSelRow = new QHBoxLayout();
    thePaletteCombo = new QComboBox();
    thePaletteCombo->addItem("Grayscale (default)");
    connect(thePaletteCombo, SIGNAL(currentIndexChanged(int)),
            this, SLOT(onPaletteSelected(int)));
    palSelRow->addWidget(thePaletteCombo);

    QPushButton *loadBtn = new QPushButton("Load JSON...");
    connect(loadBtn, &QPushButton::clicked, this, &GenesisSpriteViewerWidget::onLoadJson);
    palSelRow->addWidget(loadBtn);
    palLayout->addLayout(palSelRow);

    QPushButton *readBtn = new QPushButton("Read palette at cursor");
    connect(readBtn, &QPushButton::clicked,
            this, &GenesisSpriteViewerWidget::onReadPaletteAtCursor);
    palLayout->addWidget(readBtn);

    theSwatch = new PaletteSwatchWidget();
    palLayout->addWidget(theSwatch);

    palGroup->setLayout(palLayout);
    layout->addWidget(palGroup);

    // Sprite display
    theSpriteDisplay = new QLabel("No tile data");
    theSpriteDisplay->setAlignment(Qt::AlignCenter);
    theSpriteDisplay->setMinimumSize(64, 64);
    theSpriteDisplay->setSizePolicy(QSizePolicy::Expanding, QSizePolicy::Expanding);
    theSpriteDisplay->setStyleSheet("background-color: #202020; border: 1px solid #444;");

    QScrollArea *scroll = new QScrollArea();
    scroll->setWidget(theSpriteDisplay);
    scroll->setWidgetResizable(true);
    scroll->setMinimumHeight(128);
    layout->addWidget(scroll, 1);

    // Info label
    theInfoLabel = new QLabel("");
    theInfoLabel->setStyleSheet("color: #888; font-size: 11px;");
    layout->addWidget(theInfoLabel);

    setLayout(layout);
}

void GenesisSpriteViewerWidget::notifyViewChanged(ViewFrame *frame)
{
    theFrame = frame;
    if (frame)
    {
        auto view = frame->getCurrentBinaryView();
        if (view)
            theData = view;
    }
    refreshDisplay();
}

void GenesisSpriteViewerWidget::notifyOffsetChanged(uint64_t offset)
{
    if (offset != theCurrentOffset)
    {
        theCurrentOffset = offset;
        theAddrLabel->setText(QString("0x%1").arg(offset, 8, 16, QChar('0')).toUpper());
        refreshDisplay();
    }
}

void GenesisSpriteViewerWidget::onGridChanged(int)
{
    theGridW = theWidthSpin->value();
    theGridH = theHeightSpin->value();
    refreshDisplay();
}

void GenesisSpriteViewerWidget::onZoomChanged(int value)
{
    theZoom = value;
    refreshDisplay();
}

void GenesisSpriteViewerWidget::onPaletteSelected(int index)
{
    if (index == 0)
    {
        theActivePalette = grayscalePalette();
    }
    else
    {
        QString name = thePaletteCombo->itemText(index);
        if (theLoadedPalettes.contains(name))
            theActivePalette = theLoadedPalettes[name];
    }
    theSwatch->setPalette(theActivePalette);
    refreshDisplay();
}

void GenesisSpriteViewerWidget::onLoadJson()
{
    QString path = QFileDialog::getOpenFileName(
        this, "Open Game Definition JSON", QString(),
        "JSON Files (*.json);;All Files (*)");

    if (path.isEmpty())
        return;

    QFile f(path);
    if (!f.open(QIODevice::ReadOnly))
        return;

    QJsonDocument doc = QJsonDocument::fromJson(f.readAll());
    if (doc.isNull())
        return;

    QJsonObject root = doc.object();
    theLoadedPalettes.clear();

    // Normalized format: palettes dict
    if (root.contains("palettes") && root["palettes"].isObject())
    {
        QJsonObject pals = root["palettes"].toObject();
        for (auto it = pals.begin(); it != pals.end(); ++it)
        {
            QJsonObject palObj = it.value().toObject();
            QString name = palObj["name"].toString(it.key());

            // Try CRAM values first
            QJsonArray cramArr = palObj["cram_values"].toArray();
            if (cramArr.size() >= 16)
            {
                QVector<QColor> colors;
                for (int i = 0; i < 16; ++i)
                {
                    bool ok = false;
                    uint16_t word = cramArr[i].toString("0").toUInt(&ok, 16);
                    colors.append(decodeCramColor(word));
                }
                theLoadedPalettes[name] = colors;
            }
            else
            {
                // Try reading from ROM offset
                uint32_t romOff = 0;
                QString offStr = palObj["rom_offset"].toString();
                if (!offStr.isEmpty())
                {
                    bool ok = false;
                    romOff = offStr.toUInt(&ok, 0);
                    if (!ok) romOff = 0;
                }
                if (romOff > 0 && romOff < 0xFF0000 && theData)
                {
                    BinaryNinja::DataBuffer buf = theData->ReadBuffer(romOff, 32);
                    if (buf.GetLength() == 32)
                    {
                        QByteArray palBytes((const char *)buf.GetData(), 32);
                        theLoadedPalettes[name] = decodeCramPalette(palBytes);
                    }
                }
            }
        }
    }

    // Update combo
    thePaletteCombo->blockSignals(true);
    thePaletteCombo->clear();
    thePaletteCombo->addItem("Grayscale (default)");
    for (auto it = theLoadedPalettes.begin(); it != theLoadedPalettes.end(); ++it)
        thePaletteCombo->addItem(it.key());
    thePaletteCombo->blockSignals(false);

    if (!theLoadedPalettes.isEmpty())
        thePaletteCombo->setCurrentIndex(1);
    else
        onPaletteSelected(0);
}

void GenesisSpriteViewerWidget::onReadPaletteAtCursor()
{
    if (!theData)
        return;

    BinaryNinja::DataBuffer buf = theData->ReadBuffer(theCurrentOffset, 32);
    if (buf.GetLength() < 32)
        return;

    QByteArray palBytes((const char *)buf.GetData(), 32);
    QString name = QString("ROM@0x%1").arg(theCurrentOffset, 6, 16, QChar('0')).toUpper();
    theLoadedPalettes[name] = decodeCramPalette(palBytes);

    thePaletteCombo->blockSignals(true);
    thePaletteCombo->addItem(name);
    thePaletteCombo->blockSignals(false);
    thePaletteCombo->setCurrentIndex(thePaletteCombo->count() - 1);
}

void GenesisSpriteViewerWidget::refreshDisplay()
{
    if (!theData)
    {
        theSpriteDisplay->setPixmap(QPixmap());
        theSpriteDisplay->setText("No BinaryView attached");
        theInfoLabel->setText("");
        return;
    }

    int totalTiles = theGridW * theGridH;
    int neededBytes = totalTiles * BYTES_PER_TILE;

    BinaryNinja::DataBuffer buf = theData->ReadBuffer(theCurrentOffset, neededBytes);
    if ((int)buf.GetLength() < neededBytes)
    {
        theSpriteDisplay->setPixmap(QPixmap());
        theSpriteDisplay->setText(
            QString("Not enough data\nNeed %1 bytes at 0x%2")
            .arg(neededBytes)
            .arg(theCurrentOffset, 8, 16, QChar('0')).toUpper());
        theInfoLabel->setText("");
        return;
    }

    QByteArray tileData((const char *)buf.GetData(), neededBytes);
    QPixmap pixmap = renderSpriteGrid(tileData, theGridW, theGridH,
                                       theActivePalette, theZoom);

    if (!pixmap.isNull())
    {
        theSpriteDisplay->setText("");
        theSpriteDisplay->setPixmap(pixmap);
    }
    else
    {
        theSpriteDisplay->setPixmap(QPixmap());
        theSpriteDisplay->setText("Render failed");
    }

    int pixW = theGridW * TILE_W;
    int pixH = theGridH * TILE_H;
    theInfoLabel->setText(
        QString("%1x%2 tiles = %3x%4 px | %5 bytes (0x%6)")
        .arg(theGridW).arg(theGridH)
        .arg(pixW).arg(pixH)
        .arg(neededBytes)
        .arg(neededBytes, 0, 16).toUpper());
}


// ---------------------------------------------------------------------------
// Sidebar widget type
// ---------------------------------------------------------------------------

GenesisSpriteViewerWidgetType::GenesisSpriteViewerWidgetType()
    : SidebarWidgetType([] {
        // Simple grid icon
        QImage icon(16, 16, QImage::Format_ARGB32);
        icon.fill(Qt::transparent);
        QPainter p(&icon);
        p.setPen(QColor(200, 200, 200));
        for (int gx = 0; gx < 2; ++gx)
        {
            for (int gy = 0; gy < 2; ++gy)
            {
                int x = 1 + gx * 7;
                int y = 1 + gy * 7;
                QColor fill = (gx + gy) % 2 == 0
                    ? QColor(180, 180, 220) : QColor(100, 100, 160);
                p.fillRect(x, y, 6, 6, fill);
                p.drawRect(x, y, 6, 6);
            }
        }
        p.end();
        return icon;
    }(), "Sprite Viewer")
{
}

SidebarWidget *GenesisSpriteViewerWidgetType::createWidget(
    ViewFrame *frame, BinaryViewRef data)
{
    return new GenesisSpriteViewerWidget("Sprite Viewer", frame, data);
}
