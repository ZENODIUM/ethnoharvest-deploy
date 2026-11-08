#Remove all objects
rm(list=ls(all=TRUE))

#Load needed Packages
library(dplyr)
library(pracma)

#Data preparation####

#Select the data directory where you saved the raw data files.
data_dir <- choose.dir()

#Load phenology raw data (2019-2023)
d2019 <-read.table(file.path(data_dir, "rawdata_PhenObs_2019.csv"), sep=";",header=T ,fill=TRUE)
d2019$Year <- c(2019)
d2020 <-read.table(file.path(data_dir, "rawdata_PhenObs_2020.csv"), sep=";",header=T ,fill=TRUE)
d2020$Year <- c(2020)
d2021 <-read.table(file.path(data_dir, "rawdata_PhenObs_2021.csv"), sep=";",header=T ,fill=TRUE)
d2021$Year <- c(2021)
d2022 <-read.table(file.path(data_dir, "rawdata_PhenObs_2022.csv"), sep=";",header=T ,fill=TRUE)
d2022$Year <- c(2022)
d2023 <-read.table(file.path(data_dir, "rawdata_PhenObs_2023.csv"), sep=";",header=T ,fill=TRUE)
d2023$Year <- c(2023)

#Combine the different years into one dataset
phen<-rbind(d2019,d2020,d2021,d2022,d2023) 

#Add an identifier with Species_ID and Year
phen$Ident <-paste(phen$Species_ID, phen$Year, sep="_") #Add an identifier with Species_ID and Year

#Delete NAs from the column "Flowering.Intensity"
phen1 <- phen[!(is.na(phen$Flowering.intensity)), ]

#Subset for only observations with more than 24 weeks of monitoring
number_yes <- phen1 %>% group_by(Ident) %>% summarise(number_yes= length(Botanic_Garden))
phen1 <-merge(phen1,number_yes, by=c("Ident"))
phen1<-phen1 %>% filter(number_yes >24)

#Subset for only Ident which flowered
phen2<-phen1 %>%dplyr::group_by(Ident) %>% dplyr::summarise(mean_flowering = mean(Flowering.intensity, na.rm=T))
phen2<-phen2 %>% dplyr::filter(mean_flowering >0)
phen1<-merge(phen1,phen2, by=c("Ident"))


#Calculation of the Flowering Curve characteristics, i.e. Maximum flowering intensity, Number of flowering peaks####

#Preparation of an empty data frame
output1 <- data.frame(max_flowering_intensity=NA,number_peaks=NA,Ident=NA)

#Vector of all Ident (Species monitored in one year in one garden)
Ident<-phen1$Ident %>% unique()

for (i in Ident)
{
  phen_sub<- phen1 %>% filter(Ident == (i)) #Subset corresponding to Ident
  
  #Creating the smooth curved
  weights <- ifelse(phen_sub$y == max(phen_sub$y), 100, 1)
  spline<-smooth.spline(phen_sub$Doy,phen_sub$Flowering.intensity, spar=0.4 )
  spline_df <- data.frame(spline$x, spline$y)
  spline_filter<- spline_df %>% filter(spline.y > 1)
  
  #Number of peaks
  z <- findpeaks(spline$y,minpeakdistance=7,minpeakheight=max(spline$y)/5)
  
  if(is.null(nrow(z))){
    number_peaks<-0}else{
      number_peaks<-nrow(z)}
  
  #Maximum flowering intensity
  max_DOY_df <- spline_filter %>% filter(spline.y == max(spline.y))
  max_DOY <- max_DOY_df[1,1]
  max_flowering_intensity <- max_DOY_df[1,2]

  
  d <- as.data.frame(cbind(max_flowering_intensity,number_peaks))
  d$Ident <- i
  output1<-rbind(output1,d)
}

#Only select curves for which all characteristics are available
Curve_Shape<-output1[complete.cases(output1),]



write.table(Curve_Shape, file = file.path(data_dir, "Shape_values_Overview.csv"), sep=";",dec = ".", row.names = FALSE)
